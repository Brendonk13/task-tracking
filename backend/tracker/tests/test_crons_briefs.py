import json

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

    sessions_when_claude_started: list[list[dict]] = []
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
        side_effect=lambda call: sessions_when_claude_started.append(
            client.get("/sessions").json()
        ),
    )

    run_cron(client)

    assert fake_processes.calls_to("claude"), "no claude process was started at all"

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    already_listed = {
        session["session_id"]: session
        for snapshot in sessions_when_claude_started
        for session in snapshot
    }
    for_con7 = [s for s in already_listed.values() if s["ticket_id"] == con7["id"]]
    assert len(for_con7) == 1, already_listed

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
