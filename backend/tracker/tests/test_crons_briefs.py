import json
from pathlib import Path

import pytest

from tracker.tests import fakes
from tracker.tests.conftest import run_cron

pytestmark = pytest.mark.django_db

BRIEF_REPO = "mosaic-avantos/avantos"


def test_new_ticket_gets_a_managed_session_linked_to_it_before_claude_is_invoked(
    client, cron_settings, fake_processes, linear_transport
):
    """The session row exists before the process it describes does (§4 C2.1).

    A human watching the sessions page must never see a ``claude`` running with no
    row to explain it — so the row is written first, already linked to its ticket
    and already marked ``running``, and only then is the process started. The fake
    ``claude`` therefore asks the API what it can see at the exact moment it is
    invoked; the assertions are made against that snapshot, not against the state
    after the run, which would say nothing about ordering.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    # What /sessions showed at the moment each claude was started, keyed by the
    # --session-id that call carried: a run only makes a claim about its own session.
    listed_when_started: dict[str, list[dict]] = {}
    fake_processes.on(
        "claude",
        stdout=fakes.claude_result(
            {
                "md_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.md",
                "html_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.html",
                "next_step": "diagnose",
                "summary": "CON-7 is a bug in the external handoff dispatcher.",
            }
        ),
        side_effect=lambda call: listed_when_started.__setitem__(
            call.arg_after("--session-id"), client.get("/sessions").json()
        ),
    )

    run_cron(client)

    assert fake_processes.calls_to("claude"), "no claude process was started at all"

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    con7_session_id = next(
        s["session_id"]
        for s in client.get("/sessions").json()
        if s["ticket_id"] == con7["id"]
    )
    for_con7 = [
        s
        for s in listed_when_started[con7_session_id]
        if s["session_id"] == con7_session_id
    ]
    assert len(for_con7) == 1, listed_when_started[con7_session_id]

    session = for_con7[0]
    assert session["purpose"] == "ticket_brief"
    assert session["status"] == "running"
    assert session["model"] == "opus"
    assert session["effort"] == "high"
    assert session["directory"] == cron_settings.REPO_DIRS[BRIEF_REPO]


def test_claude_is_invoked_headless_with_the_ticket_brief_prompt_model_effort_and_session_id(
    client, cron_settings, fake_processes, linear_transport
):
    """The argv the real ``claude`` would have been started with (§4 C2.2).

    This is the whole contract with the CLI: headless ``-p`` with the skill prompt,
    the model and effort the session row advertises, the pre-generated session id so
    ``claude --resume`` reaches this transcript, JSON output against a schema that
    demands the two brief paths back, no permission prompts, write access to the
    briefs directory, and a cost ceiling. Every expected value is read from
    ``cron_settings`` or from the API, never copied by hand.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on(
        "claude",
        stdout=fakes.claude_result(
            {
                "md_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.md",
                "html_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.html",
                "next_step": "diagnose",
                "summary": "CON-7 is a bug in the external handoff dispatcher.",
            }
        ),
    )

    run_cron(client)

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    con7_session_ids = {
        session["session_id"]
        for session in client.get("/sessions").json()
        if session["ticket_id"] == con7["id"]
    }
    assert len(con7_session_ids) == 1, con7_session_ids
    session_id = con7_session_ids.pop()

    invocations = [
        call
        for call in fake_processes.calls_to("claude")
        if call.arg_after("--session-id") == session_id
    ]
    assert len(invocations) == 1, fake_processes.argvs_to("claude")
    call = invocations[0]

    assert "-p" in call.argv
    prompt = call.arg_after("-p")
    assert prompt is not None and prompt.startswith("/ticket-brief CON-7"), prompt
    assert call.arg_after("--model") == "opus"
    assert call.arg_after("--effort") == "high"
    assert call.arg_after("--output-format") == "json"
    assert call.arg_after("--permission-prompts") == "none"

    schema = json.loads(call.arg_after("--json-schema") or "")
    assert {"md_path", "html_path"} <= set(schema.get("required", [])), schema

    assert cron_settings.BRIEFS_DIR in call.values_after("--add-dir")
    assert call.arg_after("--max-budget-usd") == str(cron_settings.CLAUDE_MAX_BUDGET_USD)


def test_ticket_brief_session_can_read_linear_but_every_linear_write_tool_is_disallowed(
    client, cron_settings, fake_processes, linear_transport
):
    """The brief run reads Linear and can never write anywhere (§4 C2.3, §6).

    A brief is research: the session must reach Linear's ``get_*``/``list_*`` tools or
    it has nothing to describe, and it must not be able to comment on the issue, push,
    or answer a PR on the way past. ``--permission-prompts none`` denies silently, so
    the allow and deny lists are the only guard there is, and the appended system
    prompt states the same rule in words for the model itself. The tools are asserted
    as whole argv values, the way the real binary would receive them — a substring
    match would pass on a list that only mentioned them inside another string.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on(
        "claude",
        stdout=fakes.claude_result(
            {
                "md_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.md",
                "html_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.html",
                "next_step": "diagnose",
                "summary": "CON-7 is a bug in the external handoff dispatcher.",
            }
        ),
    )

    run_cron(client)

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    con7_session_ids = {
        session["session_id"]
        for session in client.get("/sessions").json()
        if session["ticket_id"] == con7["id"]
    }
    assert len(con7_session_ids) == 1, con7_session_ids
    session_id = con7_session_ids.pop()

    invocations = [
        call
        for call in fake_processes.calls_to("claude")
        if call.arg_after("--session-id") == session_id
    ]
    assert len(invocations) == 1, fake_processes.argvs_to("claude")
    call = invocations[0]

    allowed = call.values_after("--allowedTools")
    assert "mcp__claude_ai_Linear__get_*" in allowed, call.argv
    assert "mcp__claude_ai_Linear__list_*" in allowed, call.argv

    disallowed = call.values_after("--disallowedTools")
    for write_tool in (
        "mcp__claude_ai_Linear__create_*",
        "mcp__claude_ai_Linear__update_*",
        "mcp__claude_ai_Linear__delete_*",
        "mcp__claude_ai_Linear__save_*",
        "Bash(gh pr comment:*)",
        "Bash(git push:*)",
    ):
        assert write_tool in disallowed, call.argv

    system_prompt = call.arg_after("--append-system-prompt")
    assert system_prompt is not None, call.argv
    assert "READ-ONLY" in system_prompt.upper(), system_prompt


def test_brief_paths_from_structured_output_are_stored_and_served(
    client, cron_settings, fake_processes, linear_transport
):
    """The brief the skill wrote is findable afterwards, from the API alone (§4 C2.4).

    The point of spawning the session is the artefact it leaves behind, so the fake
    ``claude`` does exactly what the real skill does: it writes the ``.md`` and the
    ``.html`` into ``BRIEFS_DIR`` and then names those two absolute paths in its
    structured output. The envelope around that output is the captured one, so the
    keys and nesting are the real binary's, not a guess. Afterwards a human must be
    able to open the brief from the ticket page — hence the stored path and the
    served bytes are both asserted — and the session that produced it must read as
    done, with something to show for itself in ``last_message``.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    briefs_dir = Path(cron_settings.BRIEFS_DIR)
    md_path = briefs_dir / "2026-09-17-CON-7.md"
    html_path = briefs_dir / "2026-09-17-CON-7.html"
    html_body = "<!doctype html><html><body><h1>CON-7</h1><p>Handoff brief.</p></body></html>"

    envelope = fakes.fixture_json("claude/ticket_brief_ok.json")
    structured = dict(envelope["structured_output"])
    structured["md_path"] = str(md_path)
    structured["html_path"] = str(html_path)
    envelope["structured_output"] = structured
    envelope["result"] = json.dumps(structured)

    def write_the_brief(call) -> None:
        md_path.write_text("# CON-7\n\nHandoff brief.\n")
        html_path.write_text(html_body)

    fake_processes.on(
        "claude", stdout=json.dumps(envelope), side_effect=write_the_brief
    )

    run_cron(client)

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    detail = client.get(f"/tickets/{con7['id']}").json()
    assert detail.get("brief"), f"no brief was stored for CON-7: {detail.get('brief')!r}"
    assert detail["brief"]["html_path"] == str(html_path)

    served = client.get(f"/tickets/{con7['id']}/brief")
    assert served.status_code == 200, served.content
    assert "text/html" in served["Content-Type"], served["Content-Type"]
    assert served.content.decode() == html_body

    sessions = [
        session
        for session in client.get("/sessions").json()
        if session["ticket_id"] == con7["id"]
    ]
    assert len(sessions) == 1, sessions
    session = sessions[0]
    assert session["status"] == "finished"
    assert session["finished_at"] is not None
    assert session["last_message"], session


def test_brief_written_but_missing_from_output_is_found_by_filename_pattern(
    client, cron_settings, fake_processes, linear_transport
):
    """A silent session still leaves a brief, and we still find it (§4 C2.5).

    Sessions do the work and then forget to report it: the skill writes the ``.md``
    and the ``.html`` into ``BRIEFS_DIR`` under its own dated naming, and the run ends
    with no structured output at all — ``claude_result()`` with no structured argument
    is exactly that envelope. The artefact is on disk either way, so losing it because
    the model went quiet would be the tracker's fault, not the session's. The brief is
    therefore looked up by the name the skill uses, and the ticket page must show and
    serve it just as it would after a well-behaved run.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    briefs_dir = Path(cron_settings.BRIEFS_DIR)
    md_path = briefs_dir / "2026-09-17-CON-7.md"
    html_path = briefs_dir / "2026-09-17-CON-7.html"
    html_body = "<!doctype html><html><body><h1>CON-7</h1><p>Unreported brief.</p></body></html>"

    def write_the_brief(call) -> None:
        md_path.write_text("# CON-7\n\nUnreported brief.\n")
        html_path.write_text(html_body)

    fake_processes.on(
        "claude", stdout=fakes.claude_result(), side_effect=write_the_brief
    )

    run_cron(client)

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    detail = client.get(f"/tickets/{con7['id']}").json()
    assert detail.get("brief"), f"no brief was stored for CON-7: {detail.get('brief')!r}"
    assert detail["brief"]["html_path"] == str(html_path)

    served = client.get(f"/tickets/{con7['id']}/brief")
    assert served.status_code == 200, served.content
    assert "text/html" in served["Content-Type"], served["Content-Type"]
    assert served.content.decode() == html_body


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param({"returncode": 1, "stderr": "claude: credit balance too low"}, id="non_zero_exit"),
        pytest.param({"timeout": True}, id="timed_out"),
    ],
)
def test_failed_or_timed_out_claude_run_marks_session_failed_and_raises_cron_error(
    client, cron_settings, fake_processes, linear_transport, failure
):
    """A headless run can die two ways, and both must leave the same clean wreckage
    behind (§4 C2.6).

    Either the binary exits non-zero — no credit, a bad flag, a crash — or it never
    comes back and ``CLAUDE_SESSION_TIMEOUT_SECONDS`` kills it, which reaches us as a
    ``TimeoutExpired`` rather than a result to parse. The distinction matters to the
    code and to nobody else, so it is parametrized: in both cases the ticket must end
    up with no brief (half a brief is worse than none), the session row must stop
    claiming to be ``running`` or the sessions page shows a ghost forever, and a human
    must be told through an alert. The alert carries the session itself, nested as the
    ``Actor`` the rest of the API uses, so the alerts page can offer a resume button
    straight from the failure. The run as a whole still finishes: one dead session is
    not a dead cron.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", **failure)

    run = run_cron(client)

    assert fake_processes.calls_to("claude"), "no claude process was started at all"
    assert run["status"] == "finished", run

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    detail = client.get(f"/tickets/{con7['id']}").json()
    assert detail["brief"] is None, detail["brief"]

    sessions = [
        session
        for session in client.get("/sessions").json()
        if session["ticket_id"] == con7["id"]
    ]
    assert len(sessions) == 1, sessions
    session = sessions[0]
    assert session["status"] == "failed", session

    failures = [
        alert
        for alert in client.get("/alerts").json()
        if alert["kind"] == "cron_error"
        and (alert["session"] or {}).get("session_id") == session["session_id"]
    ]
    assert len(failures) == 1, client.get("/alerts").json()
    assert failures[0]["session"]["name"] == session["name"]
    assert failures[0]["session"]["directory"] == session["directory"]


def test_ticket_with_a_brief_or_a_running_brief_session_is_not_briefed_again(
    client, cron_settings, fake_processes, linear_transport
):
    """A brief costs real money, so a ticket is only ever briefed once (§4 C2.7).

    The cron runs on a schedule and Linear keeps returning the same active issues, so
    without a rule the tracker would re-brief every ticket every quarter of an hour and
    burn the budget on work it already has. The first run here is the well-behaved one
    from C2.4: the fake ``claude`` writes the ``.md`` and the ``.html`` into
    ``BRIEFS_DIR`` and reports those paths, so afterwards the tickets have stored briefs
    and finished sessions. The second run then sees exactly the same Linear fixtures —
    nothing new has appeared — and must start no ``claude`` at all. That is asserted by
    counting the invocations recorded at the process boundary either side of the second
    run, because it is the process, not any decision inside our own code, that spends
    the money.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    briefs_dir = Path(cron_settings.BRIEFS_DIR)
    md_path = briefs_dir / "2026-09-17-CON-7.md"
    html_path = briefs_dir / "2026-09-17-CON-7.html"

    envelope = fakes.fixture_json("claude/ticket_brief_ok.json")
    structured = dict(envelope["structured_output"])
    structured["md_path"] = str(md_path)
    structured["html_path"] = str(html_path)
    envelope["structured_output"] = structured
    envelope["result"] = json.dumps(structured)

    def write_the_brief(call) -> None:
        """Write the brief the way the skill does: one dated pair per identifier."""
        identifier = (call.arg_after("-p") or " ").split()[1]
        (briefs_dir / f"2026-09-17-{identifier}.md").write_text(f"# {identifier}\n")
        (briefs_dir / f"2026-09-17-{identifier}.html").write_text(
            f"<!doctype html><html><body><h1>{identifier}</h1></body></html>"
        )
        md_path.write_text("# CON-7\n")
        html_path.write_text("<!doctype html><html><body><h1>CON-7</h1></body></html>")

    fake_processes.on("claude", stdout=json.dumps(envelope), side_effect=write_the_brief)

    run_cron(client)

    after_first_run = len(fake_processes.calls_to("claude"))
    assert after_first_run, "no claude process was started by the first run at all"

    briefed = [
        ticket
        for ticket in client.get("/tickets").json()
        if client.get(f"/tickets/{ticket['id']}").json().get("brief")
    ]
    assert briefed, "the first run stored no brief, so there is nothing to re-brief"

    run_cron(client)

    assert len(fake_processes.calls_to("claude")) == after_first_run, (
        fake_processes.argvs_to("claude")
    )


def test_at_most_cron_max_sessions_per_run_briefs_are_spawned(
    client, cron_settings, fake_processes, linear_transport
):
    """One run may only spend ``CRON_MAX_SESSIONS_PER_RUN`` sessions (§4 C2.8, §2).

    The cron is unattended and every brief is a paid headless session, so a morning
    that imports a whole backlog must not turn into a dozen concurrent ``claude``
    processes and the afternoon's budget gone in one pass. Five new tickets arrive at
    once and the ceiling is two, so exactly two processes are started now and the
    remaining tickets simply wait: the next run takes the next two. The work is
    deferred, never dropped, which is why the second run must both start two more and
    brief tickets the first run did not — the identifiers are read back through the
    ``--session-id`` each call carried and the ticket that session is linked to, so
    the claim is about which ticket a real process was spent on.
    """
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 2
    linear_transport.serve("linear/assigned_five.json")

    briefs_dir = Path(cron_settings.BRIEFS_DIR)

    def write_the_brief(call) -> None:
        """Write the brief the way the skill does: one dated pair per identifier."""
        identifier = (call.arg_after("-p") or " ").split()[1]
        (briefs_dir / f"2026-09-17-{identifier}.md").write_text(f"# {identifier}\n")
        (briefs_dir / f"2026-09-17-{identifier}.html").write_text(
            f"<!doctype html><html><body><h1>{identifier}</h1></body></html>"
        )

    fake_processes.on(
        "claude", stdout=fakes.claude_result(), side_effect=write_the_brief
    )

    def briefed_identifiers(calls) -> list[str]:
        """Which tickets those ``claude`` calls were spent on, via their sessions."""
        ticket_of_session = {
            session["session_id"]: session["ticket_id"]
            for session in client.get("/sessions").json()
        }
        identifier_of_ticket = {
            ticket["id"]: ticket["linear_identifier"]
            for ticket in client.get("/tickets").json()
        }
        return [
            identifier_of_ticket[ticket_of_session[call.arg_after("--session-id")]]
            for call in calls
        ]

    run_cron(client)

    first_run_calls = fake_processes.calls_to("claude")
    assert len(first_run_calls) == cron_settings.CRON_MAX_SESSIONS_PER_RUN, (
        fake_processes.argvs_to("claude")
    )

    tickets = client.get("/tickets").json()
    assert len(tickets) == 5, tickets

    run_cron(client)

    all_calls = fake_processes.calls_to("claude")
    second_run_calls = all_calls[len(first_run_calls):]
    assert len(second_run_calls) == cron_settings.CRON_MAX_SESSIONS_PER_RUN, (
        fake_processes.argvs_to("claude")
    )

    briefed = briefed_identifiers(all_calls)
    assert len(set(briefed)) == len(briefed), briefed


def test_claude_is_launched_with_nested_session_env_removed(
    client, cron_settings, fake_processes, linear_transport, monkeypatch
):
    """A spawned session must not believe it is nested inside this one (§4 C2.9, §5).

    The backend is very likely started from a Claude Code session itself — that is how
    this project is built — and such a session marks its environment with ``CLAUDECODE``
    and ``CLAUDE_CODE_ENTRYPOINT``. Every child process inherits those marks by default,
    so a headless ``claude`` spawned by the cron would read them and take itself for a
    nested run. The environment each call is started with must therefore have both names
    removed. Scrubbing is not the same as starting from nothing: the session still needs
    ``PATH``, ``HOME`` and the rest of the ambient environment to find its binary and its
    credentials, so an ordinary variable set here must survive — otherwise handing over
    an empty environment would pass this test while breaking every real run.
    """
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("TASK_TRACKING_ENV_PROBE", "inherited")

    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on(
        "claude",
        stdout=fakes.claude_result(
            {
                "md_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.md",
                "html_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.html",
                "next_step": "diagnose",
                "summary": "CON-7 is a bug in the external handoff dispatcher.",
            }
        ),
    )

    run_cron(client)

    invocations = fake_processes.calls_to("claude")
    assert invocations, "no claude process was started at all"

    for call in invocations:
        env = call.env
        assert env is not None, call.argv
        assert "CLAUDECODE" not in env, sorted(env)
        assert "CLAUDE_CODE_ENTRYPOINT" not in env, sorted(env)
        assert env.get("TASK_TRACKING_ENV_PROBE") == "inherited", sorted(env)
