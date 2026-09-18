import json
import re
from pathlib import Path

import pytest

from tracker.tests import fakes
from tracker.tests.conftest import run_cron
from tracker.tests.fakes import fixture_json

pytestmark = pytest.mark.django_db

PR_REPO = "mosaic-avantos/avantos"
TRIAGED_IDENTIFIER = "CON-2386"
TRIAGE_SKILL = "/github-pr-comment-triage"


def test_pending_comments_spawn_a_triage_session_linked_to_the_ticket_in_the_repo_dir(
    client, cron_settings, fake_processes, linear_transport
):
    """A PR nobody has answered gets a triage session, and the row comes first (§4 C4.2).

    The review-comment capture is a real conversation on one PR: ``garciavalter``
    wrote three inline comments, and only one of them has an answer — a later
    ``Brendonk13`` comment pointing back at it through ``in_reply_to_id``. Two
    comments are therefore still waiting on the author, which is the whole trigger
    for triage: work a human owes the reviewer and has not done.

    What that spawns is a managed session, and as with briefs (C2.1) the row exists
    before the process it describes does, so the sessions page can never show a
    ``claude`` running with nothing to explain it. The fake ``claude`` is therefore
    asked what ``GET /sessions`` could see at the exact moment it was started, keyed
    by the ``--session-id`` that call carried; every assertion is made against that
    snapshot rather than against the state afterwards, which would say nothing about
    ordering. The session must already name itself ``pr_triage``, already be
    ``running``, already carry the model and effort it was launched with, already sit
    in the working copy configured for that PR's repo (a triage reads the diff, so
    the wrong directory reads the wrong code), and already be linked to the ticket —
    the ticket is where the resulting tasks and the block go, so a session that finds
    its ticket only at the end could not be followed while it runs.

    The ticket is raised by hand with the Linear URL of the identifier PR 10172
    carries in its branch and title, which is the only way the API lets a caller say
    which issue a ticket is; the cron links the two by itself (C3.2).

    Everything else in the run is arranged to be beside the point. Linear is served
    its ordinary pages and any brief ``claude`` is answered harmlessly; the per-run
    session budget is raised so that briefs cannot crowd the triage out, because
    sharing that budget is C4.11's subject, not this one; and only PR 10172 is served
    a comment feed, so this run has exactly one PR worth triaging. A ``claude`` is a
    triage ``claude`` when its prompt names the triage skill and the PR — the
    invocation §5 describes — which is what tells it apart from a brief run.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment``.

        The path is a single argv word (``repos/o/r/pulls/10172/comments``), so the
        match is on a piece of that word rather than on a word of its own.
        """
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    comments = fixture_json("gh/review_comments.json")
    answered = {comment.get("in_reply_to_id") for comment in comments}
    pending = [
        comment
        for comment in comments
        if comment["user"]["login"] != cron_settings.GITHUB_USER
        and comment["id"] not in answered
    ]
    assert pending, "the capture no longer has a comment waiting on an answer"

    # What /sessions showed at the moment each claude was started, keyed by the
    # --session-id that call carried: a run only makes a claim about its own session.
    listed_when_started: dict[str, list[dict]] = {}

    def snapshot(call: fakes.Call) -> None:
        listed_when_started[call.arg_after("--session-id")] = client.get("/sessions").json()

    fake_processes.on(
        "claude", stdout=fakes.claude_result(result="brief skipped"), side_effect=snapshot
    )
    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=snapshot,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]

    run_cron(client)

    def is_triage(call: fakes.Call) -> bool:
        prompt = call.arg_after("-p") or ""
        return TRIAGE_SKILL in prompt and str(number) in prompt

    triage_calls = [call for call in fake_processes.calls_to("claude") if is_triage(call)]
    assert len(triage_calls) == 1, fake_processes.argvs_to("claude")

    session_id = triage_calls[0].arg_after("--session-id")
    assert session_id in listed_when_started, listed_when_started

    listed = [
        session
        for session in listed_when_started[session_id]
        if session["session_id"] == session_id
    ]
    assert len(listed) == 1, listed_when_started[session_id]

    session = listed[0]
    assert session["purpose"] == "pr_triage"
    assert session["status"] == "running"
    assert session["model"] == "opus"
    assert session["effort"] == "high"
    assert session["directory"] == cron_settings.REPO_DIRS[PR_REPO]
    assert session["ticket_id"] == ticket_id


def test_pr_with_no_pending_comments_spawns_no_session(
    client, cron_settings, fake_processes, linear_transport
):
    """An answered review thread is not work owed to anyone, so it starts nothing (§4 C4.1).

    "Pending" is not "exists" (§1): a comment is pending while it is still waiting on
    the user. Two kinds of comment are therefore not waiting — the ones the user wrote
    himself, and the ones he has already replied to, where GitHub records the reply as
    a separate comment pointing back at the original through ``in_reply_to_id``. Only
    by rebuilding the thread from that pointer can the run tell an answered comment
    from an unanswered one; a rule that counts comments, or counts comments by other
    people, would spawn a triage session for every PR the user has ever discussed and
    keep spawning it forever, since nothing about answering a reviewer deletes what the
    reviewer wrote.

    The feed served here is the real capture with the two comments nobody answered
    removed, leaving the one exchange that did get an answer: ``garciavalter``'s
    comment and ``Brendonk13``'s reply carrying its id. Each payload is passed through
    untouched, so the run sees exactly the JSON GitHub sends, including the reply's
    own author — which is the second reason it is not pending.

    The assertion is a negative, so it is only worth anything if the PR reached the
    triage step with comments to judge; a run that imported nothing would pass it
    without ever applying the rule. ``comment_count`` on the PR is checked first for
    that reason: the comments are there, they are simply all settled. Everything else
    is arranged to be quiet — Linear serves its ordinary pages, any brief ``claude``
    is answered harmlessly, and every other PR is served an empty feed — so a triage
    ``claude``, recognised by the skill its prompt names, could only have come from
    this PR.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    captured = fixture_json("gh/review_comments.json")
    by_id = {comment["id"]: comment for comment in captured}
    replies = {
        comment["in_reply_to_id"]: comment
        for comment in captured
        if comment.get("in_reply_to_id") and comment["user"]["login"] == cron_settings.GITHUB_USER
    }
    assert replies, "the capture no longer has a comment the user answered"
    answered_id, reply = next(iter(replies.items()))
    settled = [by_id[answered_id], reply]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", json.dumps(settled))

    run_cron(client)

    prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    detail = client.get(f"/pull-requests/{prs[number]['id']}")
    assert detail.status_code == 200, detail.content
    assert detail.json()["comment_count"] > 0, detail.json()

    triage_calls = [
        call
        for call in fake_processes.calls_to("claude")
        if TRIAGE_SKILL in (call.arg_after("-p") or "")
    ]
    assert triage_calls == [], fake_processes.argvs_to("claude")


def test_triage_prompt_targets_the_pr_and_asks_for_the_analysis_json_at_a_path_under_cron_work_dir(
    client, cron_settings, fake_processes, linear_transport
):
    """The argv the real ``claude`` would have seen for a triage run (§4 C4.3, §5).

    Three things have to be true of this invocation or the run cannot use what comes
    back. The prompt has to name the skill with the arguments the skill itself takes —
    ``--pr``, ``--repo``, ``--user`` — because the skill reads the PR from GitHub, and a
    triage aimed at the wrong number or the wrong login judges comments that belong to
    somebody else. The prompt has to name a concrete absolute file for the analysis, and
    that file has to sit under ``CRON_WORK_DIR/triage/``: the run parses the JSON
    afterwards, so it must know where to look, and it must be somewhere the cron owns
    rather than inside the checkout, which the triage is forbidden to touch. That same
    directory has to appear in ``--add-dir``, or the session is asked to write to a path
    it has no access to and returns with nothing written.

    The schema is the last piece: it is what makes the reply a list of judgements rather
    than prose. Each item must carry the verdict, whether code has to change, the plan
    and the confidence, because C4.5 turns exactly those into task text, and a
    ``suggested_comment`` must be permitted but not demanded — a comment needing a code
    change has no reply to draft, so requiring one would invite the model to invent it.

    The expected repo, user and work directory are read from ``cron_settings``, and the
    PR number from the ``gh`` capture, so nothing here is a literal copied from the
    production code. The setup is C4.2's: one PR with comments still waiting on an
    answer, every other feed empty, the session budget raised so briefs cannot crowd the
    triage out.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content

    run_cron(client)

    triage_calls = [
        call
        for call in fake_processes.calls_to("claude")
        if TRIAGE_SKILL in (call.arg_after("-p") or "")
    ]
    assert len(triage_calls) == 1, fake_processes.argvs_to("claude")
    call = triage_calls[0]

    prompt = call.arg_after("-p") or ""
    expected_start = (
        f"{TRIAGE_SKILL} --pr {number} --repo {PR_REPO} --user {cron_settings.GITHUB_USER}"
    )
    assert prompt.startswith(expected_start), prompt

    triage_dir = str(Path(cron_settings.CRON_WORK_DIR) / "triage")
    analysis_paths = [
        word
        for word in re.split(r"\s+", prompt)
        if word.strip("'\"`,.;:()").startswith(triage_dir + "/")
    ]
    assert analysis_paths, (triage_dir, prompt)

    assert triage_dir in call.values_after("--add-dir"), call.argv

    schema = json.loads(call.arg_after("--json-schema") or "")
    items = schema.get("properties", {}).get("items", {})
    assert items.get("type") == "array", schema
    item = items.get("items", {})
    assert {"verdict", "needs_code_change", "plan", "confidence"} <= set(
        item.get("required", [])
    ), item
    assert "suggested_comment" in item.get("properties", {}), item
    assert "suggested_comment" not in item.get("required", []), item


def test_triage_session_cannot_post_edit_or_change_git_state(
    client, cron_settings, fake_processes, linear_transport
):
    """A triage reads the PR and writes one JSON file; it can do nothing else (§4 C4.4, §6).

    This session is pointed at a real working copy of a real repository and told to
    judge what reviewers said about an open PR, and it runs unattended with
    ``--permission-prompts none``, which means nothing will stop it at the moment it
    decides to act. The damage available to it is not hypothetical: the skill's whole
    subject is review comments, so writing a reply to one is the most natural next
    step it could take, and a reply posted by a machine in the user's name — on a PR
    other people are reading — cannot be recalled. Every reply it drafts must instead
    end up in a task behind the human gate (C4.6), which is only a guarantee if the
    session could not have posted it directly. So ``gh pr comment`` and ``gh pr
    review`` are denied, and with them the three ways ``gh api`` stops being a read:
    ``-X``/``--method`` name a verb, and ``graphql`` carries the mutation in its body.

    The second hazard is the checkout. A triage may well conclude that a reviewer is
    right and know exactly which line to change, and the plan for that change belongs
    in a task, not in the working tree a human is using for their own work. ``Edit``
    is denied so it cannot rewrite the code it is reading, and ``git commit``,
    ``git push`` and ``git checkout`` are denied so it can neither record such a
    change nor move the branch out from under whoever is on it.

    What remains has to be enough to do the job: reading the PR and its diff, the
    ``gh api`` GETs that fetch the comment feeds, and ``git fetch`` plus ``git show``,
    which are how the session reads the PR's own code when the checkout is parked on
    a different branch. Note that ``Bash(gh api:*)`` is allowed while the mutating
    forms are denied — the allow list opens the command and the deny list closes the
    ways it writes, so both halves have to be right for a read to still work.

    Tools are a fence, not an instruction, and the model behaves better when it knows
    why the fence is there, so ``--append-system-prompt`` must also say in words that
    this session never posts.

    The setup is C4.3's: one PR whose review comments are still waiting on an answer,
    every other feed empty, the per-run budget raised so a brief cannot crowd the
    triage out. The assertions are made on the argv the real ``claude`` binary would
    have received, which is the boundary this guarantee actually lives at.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content

    run_cron(client)

    triage_calls = [
        call
        for call in fake_processes.calls_to("claude")
        if TRIAGE_SKILL in (call.arg_after("-p") or "")
    ]
    assert len(triage_calls) == 1, fake_processes.argvs_to("claude")
    call = triage_calls[0]

    disallowed = call.values_after("--disallowedTools")
    for forbidden in (
        "Edit",
        "Bash(gh pr comment:*)",
        "Bash(gh pr review:*)",
        "Bash(gh api -X:*)",
        "Bash(gh api --method:*)",
        "Bash(gh api graphql:*)",
        "Bash(git commit:*)",
        "Bash(git push:*)",
        "Bash(git checkout:*)",
    ):
        assert forbidden in disallowed, (forbidden, call.argv)

    allowed = call.values_after("--allowedTools")
    for needed in (
        "Bash(gh pr view:*)",
        "Bash(gh pr diff:*)",
        "Bash(gh api:*)",
        "Bash(git fetch:*)",
        "Bash(git show:*)",
    ):
        assert needed in allowed, (needed, call.argv)

    system_prompt = call.arg_after("--append-system-prompt")
    assert system_prompt is not None, call.argv
    about_posting = [
        sentence
        for sentence in re.split(r"[.\n]", system_prompt.lower())
        if "post" in sentence
    ]
    assert about_posting, system_prompt
    assert any(
        "never" in sentence or "not" in sentence or "no " in sentence
        for sentence in about_posting
    ), about_posting


def test_code_change_items_become_tasks_blocked_by_a_human_review_gate_task(
    client, cron_settings, fake_processes, linear_transport
):
    """A triage's judgements land as tasks nobody may start before a human agrees (§4 C4.5, §5).

    The analysis that comes back is an opinion, not a decision. It was written
    unattended by a model that read a reviewer's comment and guessed what the code
    should become, and each item carries its own confidence for exactly that reason.
    Turning such an opinion straight into work a coding session can pick up would let
    one bad reading of one comment become a commit. So the first task the run creates
    is the gate — ``Human review of PR comment triage for PR #N``, depending on
    nothing, which is what makes it the one piece of work a human can actually start —
    and every task derived from the analysis depends on it. That is the whole point of
    the ``depends_on``-a-gate-task design (§1): ``blocked_by`` already drops finished
    dependencies (``test_blocked_by_drops_finished_dependencies``), so marking the
    gate done is the single act that releases the batch, and until then nothing else
    on the ticket is startable.

    Only the items that say ``needs_code_change`` become their own task. The third
    item in the analysis is a bot's review summary the triage judged invalid: there is
    nothing to build for it, only something to say, and collecting those replies is
    C4.6's subject. Creating a task for it here would put a piece of work on the
    ticket that no one can ever do.

    What goes in the description is what a person needs to decide, at the gate,
    whether the item is worth doing — and later, whoever does the work needs the same
    thing. So it carries the reviewer's comment verbatim, the verdict and the
    confidence behind it, every line of the plan (a plan missing its last step is a
    different plan), and the comment's URL, which is the only way back to the
    conversation the task came from. Titles are capped at 500 characters because they
    are built from a reviewer's prose, which has no length limit, and the column does.

    The ``claude`` fake behaves as the real skill does on the success path: it both
    returns the analysis as structured output and writes the same object to the file
    the prompt asked for (§5), so this test says nothing about which of the two the
    run reads — that choice is free, and C4.10 covers the failure path.

    Finally the tasks must be attributable. Every write derived from a session's
    output is made as that session (§1), so the history on one of these tasks must
    name the triage session — the same name ``GET /sessions`` shows for it, which is
    what the sessions page and the ticket timeline both display. A task blamed on
    ``cron`` or on ``human`` would hide which run, and which transcript, produced it.

    The setup is C4.3's: one hand-raised ticket for the PR's identifier, one PR whose
    review comments are still waiting on an answer, every other feed empty, the
    per-run budget raised so a brief cannot crowd the triage out. Every expected
    string is read out of the ``claude/triage_ok.json`` capture.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    analysis["pr"] = {**analysis["pr"], "number": number}
    code_change_items = [item for item in analysis["items"] if item["needs_code_change"]]
    assert len(code_change_items) == 2, analysis["items"]
    assert len(code_change_items) < len(analysis["items"]), "no reply-only item to ignore"

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]

    run_cron(client)

    triage_calls = [
        call
        for call in fake_processes.calls_to("claude")
        if TRIAGE_SKILL in (call.arg_after("-p") or "")
    ]
    assert len(triage_calls) == 1, fake_processes.argvs_to("claude")
    session_id = triage_calls[0].arg_after("--session-id")

    response = client.get(f"/tickets/{ticket_id}/tasks")
    assert response.status_code == 200, response.content
    tasks = response.json()
    assert tasks, "the triage created no tasks"

    gate = tasks[0]
    assert gate["title"] == f"Human review of PR comment triage for PR #{number}"
    assert gate["depends_on"] == []

    # An item that is both a code change and a drafted reply is named by two tasks: its
    # own, and the collected replies task (C4.6). Only its own is under test here.
    own_tasks = [task for task in tasks[1:] if not task["title"].startswith("Post replies")]
    for item in code_change_items:
        matching = [task for task in own_tasks if item["url"] in (task["description"] or "")]
        assert len(matching) == 1, (item["url"], own_tasks)
        task = matching[0]
        description = task["description"]
        assert item["comment"] in description, description
        assert item["verdict"] in description, description
        assert str(item["confidence"]) in description, description
        for line in item["plan"]:
            assert line in description, (line, description)
        assert task["blocked_by"] == [gate["id"]], task

    for task in tasks:
        assert len(task["title"]) <= 500, task["title"]

    sessions = {session["session_id"]: session for session in client.get("/sessions").json()}
    assert session_id in sessions, sessions

    first_item_task = next(
        task for task in own_tasks if code_change_items[0]["url"] in (task["description"] or "")
    )
    history = client.get(f"/tasks/{first_item_task['id']}").json()["history"]
    assert history, first_item_task
    assert {entry["actor"]["session_id"] for entry in history} == {session_id}
    assert {entry["actor"]["name"] for entry in history} == {sessions[session_id]["name"]}


def test_all_suggested_replies_are_collected_into_one_task_blocked_by_the_gate(
    client, cron_settings, fake_processes, linear_transport
):
    """Drafted replies never go out on their own; they queue up behind the gate (§4 C4.6, §5, §6).

    The triage session is forbidden to post (C4.4), so every reply it writes has to
    come back as text somebody still has to send. That text is the most dangerous
    thing in the analysis: it is already addressed to a reviewer, already phrased as
    the user, and would read as the user's own answer the moment it appeared on the
    PR. The guarantee §6 makes is that a draft can only ever reach GitHub through a
    person, and this is where that guarantee is kept — the drafts land in a task, and
    that task depends on the same ``Human review`` gate every other triage task
    depends on, so it is not startable until a human has agreed to the whole batch.

    They are collected into *one* task rather than one per reply because they are one
    action: whoever picks this up opens the PR once and answers the outstanding
    comments in a sitting. A task per draft would put several nearly identical items
    on the ticket, each of which could be done, forgotten or half-done separately,
    and would let the batch be partly answered while the rest stayed open.

    The count in the title is what makes the task legible on a ticket page without
    opening it, so it must be the number of drafts actually carried, not the number
    of items the triage judged. Two of the three items in the capture carry a
    ``suggested_comment``: one that also needs a code change (C4.5 gives it its own
    task; the reply is still owed) and the bot summary that needs nothing but an
    answer. The item with no draft must not be counted, or the title promises replies
    the description does not hold.

    The description has to carry both halves of each draft. The text alone is not
    enough to act on: a reply has to be posted under the comment it answers, and the
    URL is the only thing that says which one — a batch of unattributed paragraphs
    would have to be re-matched to threads by hand, which is the work this task is
    supposed to have already done.

    The setup is C4.5's: one hand-raised ticket for the PR's identifier, one PR whose
    review comments are still waiting on an answer, every other feed empty, the
    per-run budget raised so a brief cannot crowd the triage out, and the ``claude``
    fake behaving as the real skill does on the success path. Every expected string,
    and the count itself, is read out of the ``claude/triage_ok.json`` capture.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    analysis["pr"] = {**analysis["pr"], "number": number}
    reply_items = [item for item in analysis["items"] if item.get("suggested_comment")]
    assert len(reply_items) == 2, analysis["items"]
    assert len(reply_items) < len(analysis["items"]), "no draft-free item to leave out of the count"

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]

    run_cron(client)

    response = client.get(f"/tickets/{ticket_id}/tasks")
    assert response.status_code == 200, response.content
    tasks = response.json()
    assert tasks, "the triage created no tasks"

    gate = tasks[0]
    assert gate["title"] == f"Human review of PR comment triage for PR #{number}"

    expected_title = f"Post replies to {len(reply_items)} PR comments"
    replies_tasks = [task for task in tasks if task["title"] == expected_title]
    assert len(replies_tasks) == 1, (expected_title, [task["title"] for task in tasks])

    replies_task = replies_tasks[0]
    description = replies_task["description"] or ""
    for item in reply_items:
        assert item["suggested_comment"] in description, (item["id"], description)
        assert item["url"] in description, (item["id"], description)

    assert replies_task["blocked_by"] == [gate["id"]], replies_task


def test_triaged_ticket_is_blocked_flagged_and_alerted(
    client, cron_settings, fake_processes, linear_transport
):
    """A triage does not finish the work; it hands the ticket to a person (§4 C4.7, §5).

    Everything the run has produced by this point is waiting on a human: the tasks are
    all behind the gate (C4.5, C4.6), so nobody may start any of them, and the drafted
    replies are sitting in a description nobody has sent. A ticket left in whatever
    state it was in would therefore be work that looks ordinary and is in fact stalled —
    a coding session could pick it up, find every task blocked, and have no idea why.
    So the ticket is put in ``blocked`` and flagged for human eyes, which are the two
    signals this app already has for "a person is needed here": the status says the work
    cannot proceed, the flag puts the ticket on the needs-human-eyes badge and filter a
    person actually watches.

    Both writes have to say *why*, and the why is a specific pull request. A ``blocked``
    with no reason naming the PR would leave whoever opens the ticket to guess which of
    its pull requests stalled it, so the ``status_change`` entry's ``reason`` names the
    number. And both entries have to be attributed to the triage session, not to
    ``cron``: writes derived from a session's output are made as that session (§1), so
    the timeline points at the transcript that decided this, which is the only way to
    check the decision.

    The alert is the third signal and the only one that finds a person who is not
    already looking at the ticket. It has to carry all three links, because each answers
    a different question the reader has at once: the ticket is where the tasks and the
    gate are, the pull request is the conversation being answered, and the session is
    what produced the judgements — carried as the whole ``Actor`` (A1) rather than an
    id, so the alerts page can name it and render the resume button that opens its
    transcript. An alert holding only a message would make the reader search for all
    three by hand.

    Last, the pull request itself remembers which session triaged it. That is what makes
    a second look possible from the PR side: a person reading the PR row can get back to
    the run that judged its comments without going through the ticket.

    The setup is C4.5's: one hand-raised ticket for the PR's identifier, one PR whose
    review comments are still waiting on an answer, every other feed empty, the per-run
    budget raised so a brief cannot crowd the triage out, and the ``claude`` fake
    behaving as the real skill does on the success path. The session under test is
    identified by the ``--session-id`` the triage ``claude`` was launched with, so no
    assertion here depends on which session the run happened to create first.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    analysis["pr"] = {**analysis["pr"], "number": number}

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]

    run_cron(client)

    triage_calls = [
        call
        for call in fake_processes.calls_to("claude")
        if TRIAGE_SKILL in (call.arg_after("-p") or "")
    ]
    assert len(triage_calls) == 1, fake_processes.argvs_to("claude")
    session_id = triage_calls[0].arg_after("--session-id")

    sessions = {session["session_id"]: session for session in client.get("/sessions").json()}
    assert session_id in sessions, sessions
    session_name = sessions[session_id]["name"]

    detail = client.get(f"/tickets/{ticket_id}")
    assert detail.status_code == 200, detail.content
    ticket = detail.json()

    assert ticket["status"] == "blocked", ticket["status"]
    status_changes = [
        entry
        for entry in ticket["timeline"]
        if entry["kind"] == "status_change" and entry["to_status"] == "blocked"
    ]
    assert len(status_changes) == 1, ticket["timeline"]
    blocked = status_changes[0]
    assert blocked["actor"]["session_id"] == session_id, blocked
    assert blocked["actor"]["name"] == session_name, blocked
    assert f"#{number}" in (blocked["reason"] or ""), blocked

    assert ticket["needs_human_eyes"] is True, ticket
    flag_changes = [entry for entry in ticket["timeline"] if entry["kind"] == "flag_change"]
    assert len(flag_changes) == 1, ticket["timeline"]
    assert flag_changes[0]["actor"]["session_id"] == session_id, flag_changes[0]

    prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    pull_request_id = prs[number]["id"]

    alerts = client.get("/alerts")
    assert alerts.status_code == 200, alerts.content
    triaged_alerts = [alert for alert in alerts.json() if alert["kind"] == "pr_triaged"]
    assert len(triaged_alerts) == 1, alerts.json()
    alert = triaged_alerts[0]
    assert alert["ticket"] and alert["ticket"]["id"] == ticket_id, alert
    assert alert["pull_request"] and alert["pull_request"]["number"] == number, alert
    assert alert["session"], alert
    assert alert["session"]["session_id"] == session_id, alert
    assert alert["session"]["name"] == session_name, alert
    # A1/F3.5: the resume button is only rendered when the actor carries a directory.
    assert alert["session"]["directory"] == cron_settings.REPO_DIRS[PR_REPO], alert

    pr_detail = client.get(f"/pull-requests/{pull_request_id}")
    assert pr_detail.status_code == 200, pr_detail.content
    last_triage_session = pr_detail.json()["last_triage_session"]
    assert last_triage_session, pr_detail.json()
    assert last_triage_session["session_id"] == session_id, last_triage_session
    assert last_triage_session["name"] == session_name, last_triage_session


def test_triaged_comments_are_not_triaged_again_but_new_ones_start_a_second_gate(
    client, cron_settings, fake_processes, linear_transport
):
    """Triage is owed to a comment, once, and a new comment owes a new one (§4 C4.8, §1).

    A cron runs on a schedule, so this step sees the same PR again and again while the
    conversation on it stays exactly where it was. Nothing about triaging a comment
    deletes it from GitHub: the feed the second run reads is byte for byte the feed the
    first run read. If "pending" meant only "not written by the user and not answered",
    every run would start another ``claude``, write another gate and another copy of
    every task, and a ticket left open over a weekend would fill with duplicates of work
    a human already has in front of them — while quietly spending the per-run session
    budget (C4.11) on judgements that were already made. So being triaged is recorded on
    the comment itself (``triaged_by``/``triaged_at``, §1) and takes it out of the
    pending set for good.

    That record has to be per comment rather than per pull request, which is what the
    third run shows. A reviewer who adds one new comment has asked a new question, and
    nobody has judged it; the PR as a whole being "already triaged" would swallow it and
    leave real feedback unanswered. So one unanswered comment appearing is enough to
    start a second session, with its own gate — a second gate rather than reuse of the
    first, because the first may already have been reviewed and closed by a human, and
    hanging new, unreviewed judgements off a gate somebody already agreed to would let
    them through without anyone reading them.

    What must *not* repeat is the block. The ticket was put in ``blocked`` by the first
    triage and is still blocked, so the second has nothing to change; a ``status_change``
    entry recording a move from ``blocked`` to ``blocked`` would be a timeline full of
    events in which nothing happened, and would make the real transition hard to find.
    The status is already what it should be, so the only honest record is no record.

    The three feeds are built from the one capture: runs 1 and 2 are served the same
    text, and run 3 is served it with one further ``garciavalter`` comment appended —
    a copy of a real entry carrying a new ``id`` and a new ``body``, so every other key
    is shaped exactly as GitHub sends it. The later registration wins in the fake, so
    appending a reply is how the third run sees a longer feed.

    The rest of the setup is C4.5's: one hand-raised ticket for the PR's identifier,
    every other feed empty, the per-run budget raised so briefs cannot crowd the triage
    out, and the ``claude`` fake behaving as the real skill does on the success path.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    captured = fixture_json("gh/review_comments.json")
    unanswered = next(
        comment
        for comment in captured
        if comment["user"]["login"] != cron_settings.GITHUB_USER
        and not comment.get("in_reply_to_id")
    )
    # A real comment in every respect but the two things that make it a different one.
    fresh = {
        **unanswered,
        "id": unanswered["id"] + 1,
        "body": "one more thing: this branch is unreachable when the node type is empty.",
    }
    grown = [*captured, fresh]

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", json.dumps(captured))

    analysis = fixture_json("claude/triage_ok.json")["structured_output"]
    analysis["pr"] = {**analysis["pr"], "number": number}

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]

    def triage_calls() -> list[fakes.Call]:
        return [
            call
            for call in fake_processes.calls_to("claude")
            if TRIAGE_SKILL in (call.arg_after("-p") or "")
        ]

    def tasks() -> list[dict]:
        response = client.get(f"/tickets/{ticket_id}/tasks")
        assert response.status_code == 200, response.content
        return response.json()

    def gates(listed: list[dict]) -> list[dict]:
        title = f"Human review of PR comment triage for PR #{number}"
        return [task for task in listed if task["title"] == title]

    run_cron(client)

    assert len(triage_calls()) == 1, fake_processes.argvs_to("claude")
    after_first = tasks()
    assert len(gates(after_first)) == 1, after_first
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "blocked"

    run_cron(client)

    assert len(triage_calls()) == 1, fake_processes.argvs_to("claude")
    assert tasks() == after_first

    serve_feed(f"/pulls/{number}/comments", json.dumps(grown))

    run_cron(client)

    second_run_calls = triage_calls()
    assert len(second_run_calls) == 2, fake_processes.argvs_to("claude")
    session_ids = [call.arg_after("--session-id") for call in second_run_calls]
    assert len(set(session_ids)) == 2, session_ids

    after_third = tasks()
    assert len(gates(after_third)) == 2, [task["title"] for task in after_third]

    ticket = client.get(f"/tickets/{ticket_id}").json()
    assert ticket["status"] == "blocked", ticket["status"]
    status_changes = [entry for entry in ticket["timeline"] if entry["kind"] == "status_change"]
    assert len(status_changes) == 1, ticket["timeline"]


def test_empty_analysis_marks_comments_triaged_without_blocking_the_ticket(
    client, cron_settings, fake_processes, linear_transport
):
    """A triage that finds nothing owes the ticket nothing (§4 C4.9).

    The run cannot know in advance whether a reviewer's comments need an answer; that
    judgement is the session's whole job, and "nothing here needs attention" is one of
    its ordinary answers — the ``claude/triage_empty.json`` capture is a real run that
    reached exactly that conclusion, with a filled-in ``pr`` and ``summary`` and an
    empty ``items``. What must not happen is that the *asking* costs the ticket
    anything. Blocking a ticket, flagging it for human eyes and raising a
    ``pr_triaged`` alert are the three signals C4.7 defines, and every one of them says
    "a person is needed here". If they fired on an empty analysis, a schedule running
    every fifteen minutes over a quiet PR would block tickets nobody has to look at,
    fill the alerts page with nothing, and teach the reader to ignore the badge that is
    supposed to mean something. So the ticket keeps the status it had, keeps its flag
    down, gains no timeline entry, and gains no tasks: there is no gate to open, since
    there is nothing behind it.

    The comments are still triaged, though, and that is the second half. Being judged
    is a fact about the comment, not about the verdict (C4.8): a comment the triage read
    and dismissed has had its turn. If an empty result left the comments pending, the
    very next run would spawn another session on the same unchanged feed, and the same
    one after that — a PR nobody is arguing about would burn the per-run session budget
    (C4.11) forever. So the run is repeated with the same feed and must start nothing.

    The setup is C4.7's: one hand-raised ticket for the PR's identifier, one PR whose
    review comments are still waiting on an answer, every other feed empty, the per-run
    budget raised so a brief cannot crowd the triage out, and the ``claude`` fake
    behaving as the real skill does on the success path — returning the analysis and
    writing the same object to the path the prompt named. Only the analysis differs.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    analysis = fixture_json("claude/triage_empty.json")["structured_output"]
    analysis["pr"] = {**analysis["pr"], "number": number}
    assert analysis["items"] == [], analysis

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]
    status_before = client.get(f"/tickets/{ticket_id}").json()["status"]
    assert status_before != "blocked", status_before

    def triage_calls() -> list[fakes.Call]:
        return [
            call
            for call in fake_processes.calls_to("claude")
            if TRIAGE_SKILL in (call.arg_after("-p") or "")
        ]

    run_cron(client)

    assert len(triage_calls()) == 1, fake_processes.argvs_to("claude")

    tasks = client.get(f"/tickets/{ticket_id}/tasks")
    assert tasks.status_code == 200, tasks.content
    assert tasks.json() == [], tasks.json()

    ticket = client.get(f"/tickets/{ticket_id}").json()
    assert ticket["status"] == status_before, ticket["status"]
    assert ticket["needs_human_eyes"] is False, ticket
    assert [
        entry for entry in ticket["timeline"] if entry["kind"] in ("status_change", "flag_change")
    ] == [], ticket["timeline"]

    alerts = client.get("/alerts")
    assert alerts.status_code == 200, alerts.content
    assert [alert for alert in alerts.json() if alert["kind"] == "pr_triaged"] == [], alerts.json()

    # The comments were judged, so the unchanged feed is no longer work owed to anyone.
    run_cron(client)

    assert len(triage_calls()) == 1, fake_processes.argvs_to("claude")


def test_failed_triage_leaves_comments_pending_and_raises_cron_error(
    client, cron_settings, fake_processes, linear_transport
):
    """A triage that dies decides nothing, and the work stays owed (§4 C4.10).

    Everything this step writes is *derived* from one session's judgement: the tasks
    quote its verdicts, the block and the flag say a human must read them, and the
    ``pr_triaged`` alert announces that there is something to read. When the process
    exits non-zero there is no judgement at all — no analysis file, no items, nothing
    but a stderr line. So nothing may be inferred from it. A ticket blocked and flagged
    on the strength of a crashed run would send a person to a gate with no tasks behind
    it and no reason anyone could check, which is worse than silence: it is a signal
    that means nothing. The honest outcome is that the ticket is exactly as the run
    found it, and that the failure itself is what gets reported — one ``cron_error``
    alert carrying the session, so the reader can resume the transcript and see how it
    died.

    The second half is what makes this a retry rather than a loss. Being triaged is a
    fact recorded on the comment (C4.8) and only a session that actually judged it may
    record it; a failed run that marked its comments anyway would bury real reviewer
    feedback forever, because the feed never changes and the pending rule would never
    pick those comments up again. So the comments stay pending and the very next run
    owes them a triage — a fresh ``claude`` with its own ``--session-id``, since the
    dead session's id belongs to a transcript that already ended.

    The setup is C4.7's — one hand-raised ticket for the PR's identifier, one PR whose
    review comments are still waiting on an answer, every other feed empty, the per-run
    budget raised so briefs cannot crowd the triage out — with the one difference under
    test: the ``claude`` that carries the triage skill fails the way the real binary
    does, a non-zero exit with the reason on stderr and nothing on stdout.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 10
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    pull_request = next(
        pr
        for pr in fixture_json("gh/pr_list.json")
        if TRIAGED_IDENTIFIER.lower() in pr["headRefName"].lower()
    )
    number = pull_request["number"]

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    serve_feed(f"/pulls/{number}/comments", fakes.fixture_text("gh/review_comments.json"))

    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            returncode=1,
            stderr="Credit balance is too low to continue.",
        )
    )

    raised = client.post(
        "/tickets",
        json={
            "title": f"Hand-raised for {TRIAGED_IDENTIFIER}",
            "linear_url": (
                f"https://linear.app/avantos/issue/{TRIAGED_IDENTIFIER}/unskip-forms-auto-save"
            ),
            "actor_session_id": "human",
        },
    )
    assert raised.status_code == 201, raised.content
    ticket_id = raised.json()["id"]
    status_before = client.get(f"/tickets/{ticket_id}").json()["status"]
    assert status_before != "blocked", status_before

    def triage_calls() -> list[fakes.Call]:
        return [
            call
            for call in fake_processes.calls_to("claude")
            if TRIAGE_SKILL in (call.arg_after("-p") or "")
        ]

    run = run_cron(client)

    assert run["status"] == "finished", run  # one dead session is not a dead cron
    first_calls = triage_calls()
    assert len(first_calls) == 1, fake_processes.argvs_to("claude")
    session_id = first_calls[0].arg_after("--session-id")

    tasks = client.get(f"/tickets/{ticket_id}/tasks")
    assert tasks.status_code == 200, tasks.content
    assert tasks.json() == [], tasks.json()

    ticket = client.get(f"/tickets/{ticket_id}").json()
    assert ticket["status"] == status_before, ticket["status"]
    assert ticket["needs_human_eyes"] is False, ticket
    assert [
        entry for entry in ticket["timeline"] if entry["kind"] in ("status_change", "flag_change")
    ] == [], ticket["timeline"]

    alerts = client.get("/alerts")
    assert alerts.status_code == 200, alerts.content
    assert [alert for alert in alerts.json() if alert["kind"] == "pr_triaged"] == [], alerts.json()
    failures = [
        alert
        for alert in alerts.json()
        if alert["kind"] == "cron_error"
        and (alert["session"] or {}).get("session_id") == session_id
    ]
    assert len(failures) == 1, alerts.json()

    sessions = {session["session_id"]: session for session in client.get("/sessions").json()}
    assert session_id in sessions, sessions
    assert failures[0]["session"]["name"] == sessions[session_id]["name"], failures[0]

    # Nothing judged the comments, so they are still owed a triage: the next run retries.
    run_cron(client)

    second_calls = triage_calls()
    assert len(second_calls) == 2, fake_processes.argvs_to("claude")
    session_ids = [call.arg_after("--session-id") for call in second_calls]
    assert len(set(session_ids)) == 2, session_ids


def test_briefs_and_triage_share_the_per_run_session_budget(
    client, cron_settings, fake_processes, linear_transport
):
    """One run has one allowance, and both steps spend out of it (§4 C4.11, §2).

    ``CRON_MAX_SESSIONS_PER_RUN`` exists because every managed session is a paid
    headless ``claude`` started unattended, and the machine this runs on has one CPU,
    one network and one budget no matter which step asked for the process. A ceiling
    that each step kept for itself would therefore not be a ceiling at all: briefs
    would be allowed three and triage another three, so the real worst case would be
    twice the number the setting names, and it would grow again with every step added
    later. A morning that imports a backlog *and* finds a week of review comments is
    exactly when that happens — both steps are busy in the same run — so the guarantee
    has to be that the whole run starts at most ``CRON_MAX_SESSIONS_PER_RUN``
    processes, however the work divides between them.

    The arrangement makes four pieces of work and allows three. Linear serves one page
    of exactly two issues (``assigned_two.json``, ``hasNextPage`` false), so the brief
    step owes two sessions and no more; two of the captured pull requests are served a
    review-comment feed with comments still waiting on an answer, so the triage step
    owes two. Four owed, three allowed: the run must start three and leave one, and
    the next run must start exactly that one. Nothing is dropped and nothing is
    repeated, which is what the two ``--session-id`` sets say — they do not overlap,
    and together they name four distinct sessions, one per piece of work.

    Which three go first is deliberately not asserted. The steps run in a fixed order
    (tickets, then PRs), so today the first run is two briefs and one triage, but that
    is an implementation detail of the ordering, not of the budget; what the four calls
    must add up to is both briefs and both triages, which is checked at the end by
    reading the identifiers and PR numbers back out of the prompts. Each PR is served
    its own copy of the capture, re-keyed so the comment ids and URLs differ — comment
    identity is ``(kind, github_id)`` (§1), so two PRs sharing ids would silently be
    one PR's worth of comments and the run would owe three sessions, not four.
    """
    linear_transport.serve("linear/assigned_two.json")
    cron_settings.CRON_MAX_SESSIONS_PER_RUN = 3
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    imported = fixture_json("linear/assigned_two.json")["data"]["issues"]
    assert imported["pageInfo"]["hasNextPage"] is False, imported["pageInfo"]
    brief_identifiers = {issue["identifier"] for issue in imported["nodes"]}
    assert len(brief_identifiers) == 2, brief_identifiers

    triaged = fixture_json("gh/pr_list.json")[:2]
    triaged_numbers = {pull_request["number"] for pull_request in triaged}
    assert len(triaged_numbers) == 2, triaged_numbers

    owed = len(brief_identifiers) + len(triaged_numbers)
    assert owed == cron_settings.CRON_MAX_SESSIONS_PER_RUN + 1, owed

    def serve_feed(segment: str, stdout: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` (as in C4.2)."""
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=stdout,
            )
        )

    def feed_for(number: int, offset: int) -> str:
        """The captured conversation, re-keyed so it belongs to this PR alone."""
        comments = []
        for comment in fixture_json("gh/review_comments.json"):
            moved = {**comment, "id": comment["id"] + offset}
            if comment.get("in_reply_to_id"):
                moved["in_reply_to_id"] = comment["in_reply_to_id"] + offset
            moved["url"] = (
                f"https://api.github.com/repos/{PR_REPO}/pulls/comments/{moved['id']}"
            )
            moved["pull_request_url"] = (
                f"https://api.github.com/repos/{PR_REPO}/pulls/{number}"
            )
            comments.append(moved)
        return json.dumps(comments)

    serve_feed("", "[]")  # every other PR's feeds are empty, so nothing is pending there
    for index, pull_request in enumerate(triaged):
        number = pull_request["number"]
        serve_feed(f"/pulls/{number}/comments", feed_for(number, 1_000 * (index + 1)))

    briefs_dir = Path(cron_settings.BRIEFS_DIR)

    def write_the_brief(call: fakes.Call) -> None:
        """Write the brief the way the skill does: one dated pair per identifier."""
        identifier = (call.arg_after("-p") or " ").split()[1]
        (briefs_dir / f"2026-09-17-{identifier}.md").write_text(f"# {identifier}\n")
        (briefs_dir / f"2026-09-17-{identifier}.html").write_text(
            f"<!doctype html><html><body><h1>{identifier}</h1></body></html>"
        )

    analysis = fixture_json("claude/triage_ok.json")["structured_output"]

    def write_the_analysis(call: fakes.Call) -> None:
        """Do what the skill does: write the analysis to the path the prompt named."""
        triage_dir = Path(cron_settings.CRON_WORK_DIR) / "triage"
        prompt = call.arg_after("-p") or ""
        wanted = [
            word.strip("'\"`,.;:()")
            for word in re.split(r"\s+", prompt)
            if word.strip("'\"`,.;:()").startswith(str(triage_dir) + "/")
        ]
        assert wanted, (triage_dir, prompt)
        path = Path(wanted[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis))

    fake_processes.on("claude", stdout=fakes.claude_result(), side_effect=write_the_brief)
    fake_processes.replies.append(
        fakes.Reply(
            match=lambda argv: argv[0].endswith("claude")
            and any(TRIAGE_SKILL in arg for arg in argv),
            stdout=fakes.claude_result(analysis),
            side_effect=write_the_analysis,
        )
    )

    # Each PR needs a ticket to hang its triage on, and only an identifier in the
    # linear_url can say which issue a hand-raised ticket belongs to (C1.7, C3.2).
    for pull_request in triaged:
        identifier = re.search(r"CON-\d+", pull_request["headRefName"], re.IGNORECASE)
        assert identifier, pull_request["headRefName"]
        key = identifier.group(0).upper()
        raised = client.post(
            "/tickets",
            json={
                "title": f"Hand-raised for {key}",
                "linear_url": f"https://linear.app/avantos/issue/{key}/hand-raised",
                "actor_session_id": "human",
            },
        )
        assert raised.status_code == 201, raised.content

    run_cron(client)

    first_run = fake_processes.calls_to("claude")
    assert len(first_run) == cron_settings.CRON_MAX_SESSIONS_PER_RUN, (
        fake_processes.argvs_to("claude")
    )

    run_cron(client)

    every_call = fake_processes.calls_to("claude")
    second_run = every_call[len(first_run):]
    assert len(second_run) == owed - cron_settings.CRON_MAX_SESSIONS_PER_RUN, (
        fake_processes.argvs_to("claude")
    )

    first_ids = {call.arg_after("--session-id") for call in first_run}
    second_ids = {call.arg_after("--session-id") for call in second_run}
    assert first_ids & second_ids == set(), (first_ids, second_ids)
    assert len(first_ids | second_ids) == owed, (first_ids, second_ids)

    # Four sessions, and they are the four pieces of work: both briefs, both triages.
    prompts = [call.arg_after("-p") or "" for call in every_call]
    briefed = {
        prompt.split()[1] for prompt in prompts if prompt.startswith("/ticket-brief ")
    }
    assert briefed == brief_identifiers, prompts
    triage_prompts = [prompt for prompt in prompts if prompt.startswith(TRIAGE_SKILL)]
    assert len(triage_prompts) == len(triaged_numbers), prompts
    assert {
        int(re.search(r"--pr (\d+)", prompt).group(1)) for prompt in triage_prompts
    } == triaged_numbers, triage_prompts
