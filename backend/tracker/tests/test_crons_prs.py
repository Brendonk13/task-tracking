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
