import json

import pytest

from tracker.tests import fakes
from tracker.tests.conftest import run_cron
from tracker.tests.fakes import fixture_json

pytestmark = pytest.mark.django_db

PR_REPO = "mosaic-avantos/avantos"


def test_open_prs_by_the_github_user_are_imported_and_listed(
    client, cron_settings, fake_processes, linear_transport
):
    """The run learns about the user's open PRs by asking ``gh`` (§4 C3.1).

    Two things are under test, and both are boundaries rather than internals. The
    first is the question we put to GitHub: ``gh pr list`` narrowed server-side to
    the configured repo, the configured author and open PRs only, asking for every
    field a ``PullRequest`` row is made of — anything missing from ``--json`` is a
    column that could never be filled. The second is the answer showing up at
    ``GET /pull-requests``, one row per PR, with the values ``gh`` actually printed,
    read back out of the fixture rather than re-derived here. ``state`` is the one
    value that is not passed through: ``gh`` shouts ``OPEN`` and we store the
    lower-cased form the rest of the API uses.

    The ticket step runs first and is not the subject, so Linear is served its
    ordinary pages and any brief ``claude`` it spawns is answered harmlessly.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    run_cron(client)

    listed = [
        call for call in fake_processes.calls_to("gh") if "pr" in call.argv and "list" in call.argv
    ]
    assert len(listed) == 1, fake_processes.argvs_to("gh")
    call = listed[0]
    assert call.argv[1:3] == ["pr", "list"], call.argv
    assert call.arg_after("--repo") == PR_REPO, call.argv
    assert call.arg_after("--author") == cron_settings.GITHUB_USER, call.argv
    assert call.arg_after("--state") == "open", call.argv

    asked_for = set((call.arg_after("--json") or "").split(","))
    assert {
        "number",
        "title",
        "url",
        "body",
        "headRefName",
        "headRefOid",
        "state",
        "author",
    } <= asked_for, call.argv

    prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    expected = fixture_json("gh/pr_list.json")
    assert sorted(prs) == sorted(pr["number"] for pr in expected), prs

    for pull_request in expected:
        row = prs[pull_request["number"]]
        assert row["repo"] == PR_REPO
        assert row["url"] == pull_request["url"]
        assert row["title"] == pull_request["title"]
        assert row["branch"] == pull_request["headRefName"]
        assert row["head_sha"] == pull_request["headRefOid"]
        assert row["author"] == pull_request["author"]["login"]
        assert row["state"] == "open"
        assert pull_request["state"] == "OPEN", "the fixture no longer shouts its state"


def test_pr_is_linked_to_the_ticket_whose_identifier_appears_in_branch_title_or_body_case_insensitively(  # noqa: E501
    client, cron_settings, fake_processes, linear_transport
):
    """A PR finds its ticket by the Linear identifier it carries (§4 C3.2).

    GitHub spells the identifier three different ways in the same PR: the branch
    lower-cases it (``brendonkeirle/con-2513-…``), the title shouts it
    (``[CON-2386] …``) and the body writes it in prose. All three are the same
    identifier, so the match is case-insensitive, and the places are tried in that
    order — branch, then title, then body — which is why PR 10172 belongs to the
    CON-2386 its branch and title name and not to the CON-2416 its body only
    mentions in passing. A PR whose identifier names no ticket here (PR 9234's
    CON-2223) links to nothing rather than to something that looks close.

    The three tickets are raised by hand with their Linear URLs, which is the only
    way the API lets a caller say which issue a ticket is — ``linear_identifier``
    is never accepted on the wire — so the matcher reads the identifier out of
    ``linear_url``, the same way the import does when it adopts a ticket (C1.7).
    Linear is served its ordinary pages and any brief ``claude`` is answered
    harmlessly, because neither is the subject here.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    def raise_ticket(identifier: str, slug: str) -> int:
        response = client.post(
            "/tickets",
            json={
                "title": f"Hand-raised for {identifier}",
                "linear_url": f"https://linear.app/avantos/issue/{identifier}/{slug}",
                "actor_session_id": "human",
            },
        )
        assert response.status_code == 201, response.content
        return response.json()["id"]

    saml = raise_ticket("CON-2513", "add-sei-public-key-for-encrypting-saml")
    flaky = raise_ticket("CON-2386", "unskip-forms-auto-save-validation-test")
    dsl_race = raise_ticket("CON-2416", "wait-for-the-updating-overlay-before-typing")

    run_cron(client)

    prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    assert prs[10264].get("ticket_id") == saml, prs[10264]
    assert prs[10172].get("ticket_id") == flaky, prs[10172]
    assert prs[9234].get("ticket_id") is None, prs[9234]

    flaky_detail = client.get(f"/tickets/{flaky}").json()
    assert [pr["number"] for pr in flaky_detail.get("pull_requests", [])] == [10172]
    saml_detail = client.get(f"/tickets/{saml}").json()
    assert [pr["number"] for pr in saml_detail.get("pull_requests", [])] == [10264]
    race_detail = client.get(f"/tickets/{dsl_race}").json()
    assert race_detail.get("pull_requests", []) == []

    linked = [
        entry
        for entry in flaky_detail["timeline"]
        if entry["kind"] == "field_change" and entry["actor"]["session_id"] == "cron"
    ]
    assert len(linked) == 1, flaky_detail["timeline"]
    assert "10172" in linked[0]["body"], linked[0]


def test_unlinked_pr_raises_one_pr_unlinked_alert_across_repeated_runs(
    client, cron_settings, fake_processes, linear_transport
):
    """A PR that names no ticket here is a standing flag, not a per-run event (§4 C3.3).

    The three PRs in the fixture carry CON-2513, CON-2386 and CON-2223; the only tickets
    in this database are the CON-7/8/9 the Linear pages import, so every PR arrives
    unlinked. Each one is something a person has to sort out — a ticket nobody raised, a
    typo'd branch — so each raises a ``pr_unlinked`` alert naming the PR by number, with
    the PR nested on the alert so the alerts page can link straight to it.

    The run happens twice. The second run learns nothing new, and the alert means "this
    PR is still unlinked" rather than "the cron noticed again", so the count is the same
    afterwards: one alert per unlinked PR, not one per run per PR.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    unlinked = sorted(pr["number"] for pr in fixture_json("gh/pr_list.json"))

    for run in (1, 2):
        run_cron(client)

        prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
        assert all(prs[number]["ticket_id"] is None for number in unlinked), prs

        alerts = [
            alert for alert in client.get("/alerts").json() if alert["kind"] == "pr_unlinked"
        ]
        assert sorted(alert["pull_request"]["number"] for alert in alerts) == unlinked, (
            run,
            alerts,
        )
        for alert in alerts:
            number = alert["pull_request"]["number"]
            assert alert["pull_request"]["id"] == prs[number]["id"], alert
            assert str(number) in alert["message"], alert
            assert alert["ticket"] is None, alert


def test_second_run_does_not_duplicate_prs_and_refreshes_state_of_prs_no_longer_open(
    client, cron_settings, fake_processes, linear_transport
):
    """A PR is a row keyed by ``(repo, number)``, and leaving the open list is news (§4 C3.4).

    The second run sees the same PRs again. They are the same pull requests, not new
    ones, so each updates the row it already has: ``GET /pull-requests`` still holds
    exactly one row per PR the first run imported.

    One PR is missing from the second list. A PR does not vanish from GitHub — it drops
    out of ``--state open`` because it was merged or closed — so the run has to go and
    ask ``gh pr view`` what became of it rather than leave the row saying ``open``
    forever. ``gh`` answers with the merged payload, and that is the state the row ends
    up in. The payload is a real ``pr view`` capture of another PR, rewritten to this
    PR's number and url: the shape is GitHub's, the identity is ours.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    imported = fixture_json("gh/pr_list.json")
    dropped = imported[0]
    still_open = imported[1:]

    run_cron(client)

    first_run = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    assert sorted(first_run) == sorted(pr["number"] for pr in imported), first_run
    assert first_run[dropped["number"]]["state"] == "open", first_run[dropped["number"]]

    merged = dict(fixture_json("gh/pr_view_merged.json"))
    assert merged["state"] == "MERGED", "the fixture is no longer a merged PR"
    merged["number"] = dropped["number"]
    merged["url"] = dropped["url"]
    fake_processes.on("gh", "pr", "list", stdout=json.dumps(still_open))
    fake_processes.on("gh", "pr", "view", str(dropped["number"]), stdout=json.dumps(merged))

    run_cron(client)

    second_run = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
    assert len(client.get("/pull-requests").json()) == len(imported), second_run
    assert sorted(second_run) == sorted(pr["number"] for pr in imported), second_run
    assert second_run[dropped["number"]]["id"] == first_run[dropped["number"]]["id"], second_run
    assert second_run[dropped["number"]]["state"] == "merged", second_run[dropped["number"]]
    for pull_request in still_open:
        number = pull_request["number"]
        assert second_run[number]["id"] == first_run[number]["id"], second_run[number]
        assert second_run[number]["state"] == "open", second_run[number]


def test_review_issue_and_review_summary_comments_are_imported_once(
    client, cron_settings, fake_processes, linear_transport
):
    """A PR's three comment feeds become one comment each, however often we look (§4 C3.5).

    GitHub keeps the conversation on a pull request in three places, and a triage that
    reads only one of them would answer half the review: inline comments on the diff
    (``pulls/{n}/comments``, threaded through ``in_reply_to_id``), comments on the PR as
    an issue (``issues/{n}/comments``, where the bots talk), and the reviews themselves
    (``reviews``), whose body is the "I looked at this and here is what I think" note.
    All three are paginated, so all three are read with ``gh api --paginate`` — a plain
    ``gh api`` would silently stop at thirty comments on a busy PR.

    A review with an empty body is not a comment. It is the wrapper GitHub creates around
    inline comments, and its inline comments already arrived on the first feed, so
    counting it would invent something nobody wrote: two of the three captured reviews
    are exactly that. Hence ``comment_count`` is the review comments plus the issue
    comments plus the one review that actually says something.

    Then the run happens again, over the same three feeds. Comments are identified by
    what kind they are and the id GitHub gave them, so re-reading a feed recognises every
    comment it already has and the count does not move. Without that, every cron tick
    would double the conversation and every comment would look new to triage.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    def serve_feed(segment: str, name: str) -> None:
        """Answer ``gh api`` reads whose path contains ``segment`` with a fixture.

        The path is a single argv word (``repos/o/r/pulls/9964/comments``), so the match
        is on a piece of that word rather than on a word of its own. Every PR is served
        the same capture: which PR the comments came from is not what this test is about.
        """
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=fakes.fixture_text(name),
            )
        )

    serve_feed("/pulls/", "gh/review_comments.json")
    serve_feed("/issues/", "gh/issue_comments.json")
    serve_feed("/reviews", "gh/reviews.json")

    review_comments = fixture_json("gh/review_comments.json")
    issue_comments = fixture_json("gh/issue_comments.json")
    reviews = fixture_json("gh/reviews.json")
    spoken_reviews = [review for review in reviews if review["body"].strip()]
    assert len(spoken_reviews) < len(reviews), "the fixture no longer has a body-less review"
    assert all(comment["body"].strip() for comment in review_comments + issue_comments)
    expected_count = len(review_comments) + len(issue_comments) + len(spoken_reviews)

    numbers = sorted(pr["number"] for pr in fixture_json("gh/pr_list.json"))

    for run in (1, 2):
        run_cron(client)

        prs = {pr["number"]: pr for pr in client.get("/pull-requests").json()}
        assert sorted(prs) == numbers, prs
        for number in numbers:
            response = client.get(f"/pull-requests/{prs[number]['id']}")
            assert response.status_code == 200, response.content
            detail = response.json()
            assert detail["comment_count"] == expected_count, (run, number, detail)

    api_calls = [call for call in fake_processes.calls_to("gh") if "api" in call.argv]
    for call in api_calls:
        assert call.argv[1] == "api", call.argv
        assert "--paginate" in call.argv, call.argv
        assert not any(arg.startswith("-X") or arg == "--method" for arg in call.argv), call.argv

    for number in numbers:
        paths = {arg for call in api_calls for arg in call.argv if str(number) in arg}
        assert any(f"/pulls/{number}/comments" in path for path in paths), paths
        assert any(f"/issues/{number}/comments" in path for path in paths), paths
        assert any(path.endswith(f"/pulls/{number}/reviews") for path in paths), paths


def test_github_client_only_ever_reads(
    client, cron_settings, fake_processes, linear_transport
):
    """Nothing the cron asks ``gh`` to do can change anything on GitHub (§4 C3.6, §6).

    This is the guard behind the whole design. The cron reads a PR conversation and
    then hands the findings to a human via blocked tasks; it never answers a reviewer
    itself. That promise is only worth anything at the boundary, because ``gh`` is a
    single binary where ``pr view`` and ``pr comment`` are one word apart, and a helper
    added later to "just close the stale ones" would break the promise without breaking
    any other test in this lane.

    So the whole ``gh`` surface of a full run is inspected: the listing, the detail view
    a dropped PR forces, and the three comment feeds — every call the PR steps know how
    to make. Each one must be a read. ``pr list`` and ``pr view`` are reads by name.
    ``gh api`` is a read only while it stays a GET: ``-X``/``--method`` choose a verb,
    ``-f``/``-F``/``--input`` send a body (which makes ``gh`` POST on its own), and
    ``graphql`` is where mutations live. The write subcommands are named too, so that a
    ``gh pr comment`` fails here loudly rather than passing for want of a rule.

    The second run is what brings ``gh pr view`` in: PR 10264 has left the open list, and
    the run goes to ask what became of it (C3.4). The count guard at the end keeps the
    test honest — a run that made no ``gh`` calls at all would satisfy every other
    assertion here trivially.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    def serve_feed(segment: str, name: str) -> None:
        fake_processes.replies.append(
            fakes.Reply(
                match=lambda argv, segment=segment: argv[0].endswith("gh")
                and "api" in argv
                and any(segment in arg for arg in argv),
                stdout=fakes.fixture_text(name),
            )
        )

    serve_feed("/pulls/", "gh/review_comments.json")
    serve_feed("/issues/", "gh/issue_comments.json")
    serve_feed("/reviews", "gh/reviews.json")

    imported = fixture_json("gh/pr_list.json")
    dropped = imported[0]

    run_cron(client)

    merged = dict(fixture_json("gh/pr_view_merged.json"))
    merged["number"] = dropped["number"]
    merged["url"] = dropped["url"]
    fake_processes.on("gh", "pr", "list", stdout=json.dumps(imported[1:]))
    fake_processes.on("gh", "pr", "view", str(dropped["number"]), stdout=json.dumps(merged))

    run_cron(client)

    write_switches = {"-X", "--method", "-f", "-F", "--input"}

    def is_read(argv: list[str]) -> bool:
        subcommand = argv[1:3]
        if subcommand in (["pr", "list"], ["pr", "view"]):
            return True
        if argv[1:2] != ["api"]:
            return False
        return not any(
            arg in write_switches or arg.startswith("-X") or arg == "graphql" for arg in argv[2:]
        )

    argvs = fake_processes.argvs_to("gh")
    assert argvs, "no gh call was made, so this guard proved nothing"
    assert all(is_read(argv) for argv in argvs), [
        argv for argv in argvs if not is_read(argv)
    ]
