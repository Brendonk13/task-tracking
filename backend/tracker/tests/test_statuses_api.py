import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def test_built_in_statuses_are_listed(client):
    response = client.get("/statuses")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "blocked", "is_builtin": True},
        {"name": "needs-help", "is_builtin": True},
        {"name": "planning", "is_builtin": True},
        {"name": "implementing-plan", "is_builtin": True},
        {"name": "diagnosing-ticket", "is_builtin": True},
        {"name": "needs-clarification", "is_builtin": True},
        {"name": "ready-for-pr", "is_builtin": True},
        {"name": "merged", "is_builtin": True},
        {"name": "tested-in-cloud", "is_builtin": True},
        {"name": "done", "is_builtin": True},
    ]


def test_new_ticket_has_no_status(client):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": actor})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    assert fetched.json()["status"] is None

    listing = client.get("/tickets")

    assert listing.status_code == 200
    rows = [row for row in listing.json() if row["id"] == ticket_id]
    assert len(rows) == 1
    assert rows[0]["status"] is None


def test_set_status_on_ticket_is_returned_as_current_status(client):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": actor})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    changed = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": actor},
    )

    assert changed.status_code == 200
    assert changed.json()["status"] == "planning"

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    assert fetched.json()["status"] == "planning"
