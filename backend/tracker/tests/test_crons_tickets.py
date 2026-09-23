import json

import pytest

from tracker.tests.conftest import run_cron
from tracker.tests.fakes import fixture_json

pytestmark = pytest.mark.django_db


def test_run_cron_command_creates_a_finished_cron_run_listed_by_the_api(client, fake_processes):
    """A run with no config set still records one finished run (§4 C1.1).

    Nothing is configured, so every step is skipped, but the run itself is the
    thing under test: the command drives it (S2) and the API reports it (S1).
    """
    run = run_cron(client, trigger="command")

    assert client.get("/crons/runs").json() == [run]
    assert run["status"] == "finished"
    assert run["trigger"] == "command"
    assert run["finished_at"] is not None


def test_run_without_linear_api_key_raises_a_cron_error_alert_naming_the_variable(
    client, cron_settings, fake_processes
):
    """Missing config skips the step and says which variable is missing (§2, §4 C1.2).

    Everything else is configured, so the only reason to skip the ticket import is
    the blank key — and the run itself must still finish.
    """
    cron_settings.LINEAR_API_KEY = ""

    run = run_cron(client, trigger="command")

    alerts = client.get("/alerts").json()
    assert len(alerts) == 1, alerts
    assert alerts[0]["kind"] == "cron_error"
    assert "LINEAR_API_KEY" in alerts[0]["message"]
    assert run["status"] == "finished"


def test_assigned_linear_issues_become_tickets_with_identifier_priority_url_project_and_labels(
    client, cron_settings, fake_processes, linear_transport
):
    """Each assigned active Linear issue is imported as a ticket (§4 C1.3).

    The expected values are the ones written in ``linear/assigned_page1.json``,
    spelled out per issue rather than derived the way the import does it. Importing
    a ticket is a creation, so nothing about it reads as a series of edits: the new
    ticket's timeline holds no ``field_change`` entry.
    """
    linear_transport.serve("linear/assigned_page1.json")

    run_cron(client)

    tickets = {t["linear_identifier"]: t for t in client.get("/tickets").json()}
    assert sorted(tickets) == ["CON-7", "CON-8"]

    con7 = tickets["CON-7"]
    assert con7["title"] == "External handoff dispatch drops the task id"
    assert con7["priority"] == "urgent"
    assert con7["linear_url"] == (
        "https://linear.app/avantos/issue/CON-7/external-handoff-dispatch-drops-the-task-id"
    )
    assert con7["project"] == "Action Platform"
    assert con7["labels"] == ["backend", "bug"]

    con8 = tickets["CON-8"]
    assert con8["title"] == "Document the SAML assertion signing keys"
    assert con8["priority"] == "none"
    assert con8["linear_url"] == (
        "https://linear.app/avantos/issue/CON-8/document-the-saml-assertion-signing-keys"
    )
    assert con8["project"] is None
    assert con8["labels"] == []

    detail = client.get(f"/tickets/{con7['id']}").json()
    assert [e for e in detail["timeline"] if e["kind"] == "field_change"] == []


def test_linear_request_carries_the_raw_api_key_and_only_asks_for_todo_issues(
    client, cron_settings, fake_processes, linear_transport
):
    """The request we put on the wire is safe and narrow (§4 C1.4, §5).

    Linear personal keys travel raw, so a ``Bearer `` prefix would be rejected.
    The query must also narrow the work server-side: only issues assigned to the
    configured email, and only those in Todo, whose state type Linear calls
    ``unstarted``. Page 2 is served as well because page 1 says there is more; how many
    requests that takes is C1.5's business, so only the first one is examined here.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    run_cron(client)

    request = linear_transport.requests[0]
    assert request.headers["Authorization"] == cron_settings.LINEAR_API_KEY
    assert "Bearer" not in request.headers["Authorization"]
    assert request.method == "POST"
    assert request.url.host == "api.linear.app"
    assert request.url.path == "/graphql"

    body = linear_transport.bodies[0]
    query = body["query"]
    assert 'state: { type: { eq: "unstarted" } }' in query, query

    asked = query + json.dumps(body.get("variables") or {})
    assert cron_settings.LINEAR_ASSIGNEE_EMAIL in asked, asked


def test_paginated_linear_results_are_all_imported(
    client, cron_settings, fake_processes, linear_transport
):
    """One run imports every page Linear offers, not just the first (§4 C1.5, §5).

    Page 1 ends with ``hasNextPage: true`` and a cursor, so the import must ask for
    the next page and import that one too. The issues and the cursor are read out of
    the fixtures rather than spelled out here, so this stays a statement about "all
    of both pages" — but the cursor is taken from page 1's ``pageInfo``, which is
    where the server puts it, not rebuilt from the last node the way the client
    would if it paged by itself.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    page1 = fixture_json("linear/assigned_page1.json")["data"]["issues"]
    page2 = fixture_json("linear/assigned_page2.json")["data"]["issues"]
    expected = sorted(node["identifier"] for node in page1["nodes"] + page2["nodes"])

    run_cron(client)

    tickets = client.get("/tickets").json()
    assert sorted(t["linear_identifier"] for t in tickets) == expected

    assert len(linear_transport.bodies) == 2, linear_transport.bodies
    variables = linear_transport.bodies[1].get("variables") or {}
    assert variables.get("after") == page1["pageInfo"]["endCursor"], variables


def test_second_run_imports_nothing_new_and_raises_no_new_alerts(
    client, cron_settings, fake_processes, linear_transport
):
    """The cron is safe to run every fifteen minutes (§4 C1.6).

    The second run sees exactly the same Linear issues as the first — the wire
    repeats its last page — so it must import nothing: the same tickets, no
    duplicates, and no second round of alerts. ``updated_at`` is part of the
    comparison on purpose: re-importing an unchanged issue must leave the ticket
    alone rather than rewrite it with identical values.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    run_cron(client)
    tickets_after_first_run = client.get("/tickets").json()
    alerts_after_first_run = client.get("/alerts").json()
    assert tickets_after_first_run, "the first run imported nothing to compare against"

    run_cron(client)

    assert client.get("/tickets").json() == tickets_after_first_run
    assert client.get("/alerts").json() == alerts_after_first_run


def test_hand_made_ticket_with_matching_identifier_is_adopted_not_duplicated(
    client, cron_settings, fake_processes, linear_transport
):
    """A ticket raised by hand for a Linear issue is adopted, not duplicated (§4 C1.7).

    People often raise the ticket here first and paste the Linear URL into it. When
    the import later meets the same issue it has to recognise it by the identifier
    in that URL: one ticket for CON-7, still the hand-made row (same ``id``), now
    carrying its ``linear_identifier``.
    """
    linear_url = fixture_json("linear/assigned_page1.json")["data"]["issues"]["nodes"][0]["url"]
    created = client.post(
        "/tickets",
        json={
            "title": "Handoff dispatch loses the task id",
            "linear_url": linear_url,
            "actor_session_id": "human",
        },
    )
    assert created.status_code == 201, created.content
    hand_made_id = created.json()["id"]

    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    run_cron(client)

    con7 = [t for t in client.get("/tickets").json() if t["linear_url"] == linear_url]
    assert len(con7) == 1, con7
    assert con7[0]["id"] == hand_made_id
    assert con7[0]["linear_identifier"] == "CON-7"


def test_each_new_ticket_raises_a_new_ticket_alert_linking_to_it(
    client, cron_settings, fake_processes, linear_transport
):
    """Every imported ticket announces itself on the alerts page (§4 C1.8).

    An import is only useful if a human hears about it, so each ticket the run
    creates raises exactly one ``new_ticket`` alert. The alert carries the ticket
    itself — the nested ``TicketRef`` the frontend needs to render the link — and
    names the issue in its message with the identifier and title a person would
    recognise. The expected identifiers and titles are read out of the fixtures,
    which is what Linear said, rather than out of the tickets the import wrote.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    issues = [
        node
        for name in ("linear/assigned_page1.json", "linear/assigned_page2.json")
        for node in fixture_json(name)["data"]["issues"]["nodes"]
    ]

    run_cron(client)

    tickets = {t["linear_identifier"]: t for t in client.get("/tickets").json()}
    alerts = [a for a in client.get("/alerts").json() if a["kind"] == "new_ticket"]
    assert len(alerts) == len(issues), alerts

    by_ticket_id = {a["ticket"]["id"]: a for a in alerts}
    for issue in issues:
        ticket = tickets[issue["identifier"]]
        alert = by_ticket_id[ticket["id"]]
        assert alert["ticket"] == {"id": ticket["id"], "title": ticket["title"]}
        assert issue["identifier"] in alert["message"], alert["message"]
        assert issue["title"] in alert["message"], alert["message"]


def test_linear_graphql_error_records_a_cron_error_and_the_run_still_finishes(
    client, cron_settings, fake_processes, linear_transport
):
    """A GraphQL error from Linear is isolated to its step (§4 C1.9).

    Linear answers 200 with an ``errors`` array and no data, which is how it reports
    a rejected key or a bad query. The run must survive that: nothing imported, the
    run still ``finished``, and one ``cron_error`` alert carrying the message Linear
    actually sent — read out of the fixture, so the alert has to quote the wire
    rather than some wording of our own.
    """
    linear_transport.serve("linear/error.json")
    graphql_message = fixture_json("linear/error.json")["errors"][0]["message"]

    run = run_cron(client)

    assert client.get("/tickets").json() == []

    alerts = client.get("/alerts").json()
    assert len(alerts) == 1, alerts
    assert alerts[0]["kind"] == "cron_error"
    assert graphql_message in alerts[0]["message"], alerts[0]["message"]

    assert run["status"] == "finished"


def test_cron_is_an_accepted_actor_and_cannot_be_registered_as_a_session(client):
    """``cron`` is a second reserved actor literal, like ``human`` (§1, §4 C1.10).

    The backend writes on its own behalf when it imports a ticket or links a PR, so
    it needs a name to sign those writes with. That name has to be known to the
    actor check — creating a ticket as ``cron`` is a legitimate write, not an
    unknown actor — and, exactly like ``human``, no real session may ever claim it,
    or a registered session could impersonate the backend.
    """
    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": "cron"})

    assert created.status_code == 201, created.content

    registered = client.put("/sessions/cron", json={"directory": "/home/me/proj"})

    assert registered.status_code == 422, registered.content
    assert client.get("/sessions").json() == []
