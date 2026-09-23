"""``POST /tickets/import``: a person names Linear issues by URL and they become tickets.

The cron only sweeps Todo, so this is the way in for everything else. Linear is faked
at its HTTP boundary (``linear_transport``), so the query and the parsing run for real.
"""

import httpx
import pytest

from tracker.tests.fakes import fixture_json

pytestmark = pytest.mark.django_db

CON9 = fixture_json("linear/issue_con9.json")["data"]["issue"]


def import_urls(client, *urls):
    response = client.post("/tickets/import", json={"urls": list(urls)})
    assert response.status_code == 200, response.content
    return response.json()


def test_a_started_issue_is_imported_with_its_values_tags_and_a_new_ticket_alert(
    client, cron_settings, linear_transport
):
    """The issue is in progress, which the cron would skip; a person asked, so it comes in."""
    linear_transport.serve("linear/issue_con9.json")

    [result] = import_urls(client, CON9["url"])

    assert result["outcome"] == "imported"
    assert result["url"] == CON9["url"]
    assert result["message"] is None
    ticket = client.get(f"/tickets/{result['ticket_id']}").json()
    assert ticket["linear_identifier"] == "CON-9"
    assert ticket["title"] == "Retry the webhook when the partner answers 503"
    assert ticket["priority"] == "high"
    assert ticket["project"] == "Action Platform"
    assert ticket["labels"] == ["backend"]

    alerts = client.get("/alerts").json()
    assert [(a["kind"], a["message"]) for a in alerts] == [
        ("new_ticket", "Imported CON-9: Retry the webhook when the partner answers 503")
    ]


def test_the_issue_is_asked_for_by_the_identifier_in_the_url(
    client, cron_settings, linear_transport
):
    linear_transport.serve("linear/issue_con9.json")

    import_urls(client, CON9["url"])

    [body] = linear_transport.bodies
    assert body["variables"] == {"id": "CON-9"}
    assert "issue(id: $id)" in body["query"]


def test_an_issue_already_imported_is_reported_as_existing_and_left_alone(
    client, cron_settings, linear_transport
):
    linear_transport.serve("linear/issue_con9.json")
    [first] = import_urls(client, CON9["url"])
    before = client.get(f"/tickets/{first['ticket_id']}").json()

    [again] = import_urls(client, CON9["url"])

    assert again["outcome"] == "exists"
    assert again["ticket_id"] == first["ticket_id"]
    assert client.get(f"/tickets/{first['ticket_id']}").json() == before
    assert len(client.get("/alerts").json()) == 1


def test_a_hand_made_ticket_for_the_issue_is_adopted(
    client, cron_settings, linear_transport
):
    created = client.post(
        "/tickets",
        json={
            "title": "Webhook retries",
            "linear_url": CON9["url"],
            "actor_session_id": "human",
        },
    )
    assert created.status_code == 201, created.content
    linear_transport.serve("linear/issue_con9.json")

    [result] = import_urls(client, CON9["url"])

    assert result["outcome"] == "adopted"
    assert result["ticket_id"] == created.json()["id"]
    ticket = client.get(f"/tickets/{result['ticket_id']}").json()
    assert ticket["title"] == "Webhook retries"
    assert ticket["linear_identifier"] == "CON-9"
    assert len(client.get("/tickets").json()) == 1


def test_a_url_with_no_issue_identifier_is_invalid_and_linear_is_not_asked(
    client, cron_settings, linear_transport
):
    linear_transport.serve("linear/issue_con9.json")

    [result] = import_urls(client, "https://linear.app/avantos/project/action-platform")

    assert result["outcome"] == "invalid_url"
    assert result["ticket_id"] is None
    assert result["message"]
    assert linear_transport.requests == []


def test_an_issue_linear_does_not_have_is_not_found(
    client, cron_settings, linear_transport
):
    linear_transport.serve("linear/issue_not_found.json")

    [result] = import_urls(client, "https://linear.app/avantos/issue/CON-404/gone")

    assert result["outcome"] == "not_found"
    assert result["ticket_id"] is None
    assert "CON-404" in result["message"]
    assert client.get("/tickets").json() == []


def test_each_url_is_answered_in_order_and_a_repeated_url_once(
    client, cron_settings, linear_transport
):
    linear_transport.serve("linear/issue_con9.json")
    bad = "not a url"

    results = import_urls(client, CON9["url"], bad, CON9["url"])

    assert [(r["url"], r["outcome"]) for r in results] == [
        (CON9["url"], "imported"),
        (bad, "invalid_url"),
    ]
    assert len(linear_transport.requests) == 1


def test_without_a_linear_api_key_the_import_is_refused_with_400(
    client, cron_settings, linear_transport
):
    cron_settings.LINEAR_API_KEY = ""

    response = client.post("/tickets/import", json={"urls": [CON9["url"]]})

    assert response.status_code == 400
    assert "LINEAR_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize("failure", ["auth_error", "unreachable"])
def test_linear_failing_answers_502_and_imports_nothing(
    client, cron_settings, linear_transport, failure
):
    """A rejected key is not "not found": only Linear's own not-found answer is."""
    if failure == "auth_error":
        linear_transport.serve("linear/error.json")
    else:
        linear_transport.fail(httpx.ConnectError("boom"))

    response = client.post("/tickets/import", json={"urls": [CON9["url"]]})

    assert response.status_code == 502, response.content
    assert client.get("/tickets").json() == []


def test_linear_failing_part_way_takes_back_the_urls_already_imported(
    client, cron_settings, linear_transport
):
    """The caller only sees 502, so nothing may be left behind for them to discover."""
    linear_transport.serve("linear/issue_con9.json", "linear/error.json")

    response = client.post(
        "/tickets/import",
        json={"urls": [CON9["url"], "https://linear.app/avantos/issue/CON-10/next"]},
    )

    assert response.status_code == 502, response.content
    assert client.get("/tickets").json() == []
    assert client.get("/alerts").json() == []
