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
