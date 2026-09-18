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
