import pytest

from tracker.tests import fakes
from tracker.tests.conftest import run_cron

pytestmark = pytest.mark.django_db


def test_alerts_list_hides_dismissed_by_default_and_dismiss_is_idempotent(
    client, cron_settings, fake_processes, linear_transport
):
    """The alerts page is a to-do list, so a dismissed alert leaves it (§4 C5.6).

    A run against the ordinary fixtures leaves several alerts behind: the three PRs in
    ``gh/pr_list.json`` name no ticket in this database, so each raises a
    ``pr_unlinked`` (C3.3), and the Linear pages import tickets that each announce
    themselves (C1.8). Which alerts they are does not matter here; what matters is
    that ``GET /alerts`` is the list of things still to deal with. Dismissing one is
    how a person says "handled", so it leaves the default list — otherwise the page
    only ever grows and the badge stops meaning anything. Nothing is deleted, though:
    ``?dismissed=true`` is the full history, and the dismissed alert is still in it,
    carrying the moment it was dismissed.

    Dismissing again is not an error. The frontend may retry, and two tabs may both
    have the row on screen, so a second POST is a no-op in the sense A14 gives the
    word: 200, and the stored ``dismissed_at`` is the one the first POST wrote, not a
    fresh one. A no-op that silently re-stamped the row would make the history lie
    about when the work was actually done.

    ``GET /alerts/summary`` is what the nav badge counts, so it reports how many alerts
    are still undismissed and drops by exactly one across the dismissal — the summary
    and the list are two views of one fact, not two counts that can drift. It is
    registered before ``/alerts/{id}`` (A14), or ``summary`` would be parsed as an id.
    A dismiss aimed at an alert that does not exist is a 404.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    run_cron(client)

    listed = client.get("/alerts")
    assert listed.status_code == 200, listed.content
    alerts = listed.json()
    assert len(alerts) >= 2, alerts
    assert all(alert["dismissed_at"] is None for alert in alerts), alerts

    summary = client.get("/alerts/summary")
    assert summary.status_code == 200, summary.content
    assert summary.json()["undismissed_count"] == len(alerts), summary.json()

    target = alerts[0]

    dismissed = client.post(f"/alerts/{target['id']}/dismiss")
    assert dismissed.status_code == 200, dismissed.content

    remaining = client.get("/alerts").json()
    assert [alert["id"] for alert in remaining] == [
        alert["id"] for alert in alerts if alert["id"] != target["id"]
    ], remaining
    assert client.get("/alerts/summary").json()["undismissed_count"] == len(alerts) - 1

    history = client.get("/alerts?dismissed=true")
    assert history.status_code == 200, history.content
    assert sorted(alert["id"] for alert in history.json()) == sorted(
        alert["id"] for alert in alerts
    ), history.json()
    stored = [alert for alert in history.json() if alert["id"] == target["id"]][0]
    assert stored["dismissed_at"] is not None, stored

    again = client.post(f"/alerts/{target['id']}/dismiss")
    assert again.status_code == 200, again.content

    unchanged = [
        alert for alert in client.get("/alerts?dismissed=true").json()
        if alert["id"] == target["id"]
    ][0]
    assert unchanged["dismissed_at"] == stored["dismissed_at"], unchanged
    assert client.get("/alerts/summary").json()["undismissed_count"] == len(alerts) - 1
    assert [alert["id"] for alert in client.get("/alerts").json()] == [
        alert["id"] for alert in remaining
    ]

    unknown = client.post("/alerts/9999/dismiss")
    assert unknown.status_code == 404, unknown.content
