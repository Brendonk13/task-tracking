import json

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
