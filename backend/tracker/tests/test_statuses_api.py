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


def test_custom_status_is_created_on_first_use_and_then_listed(client):
    session = register_session(client)
    actor = session["session_id"]

    def create_ticket(title):
        created = client.post("/tickets", json={"title": title, "actor_session_id": actor})
        assert created.status_code == 201
        return created.json()["id"]

    first_ticket = create_ticket("Vendor blocker")
    changed = client.post(
        f"/tickets/{first_ticket}/status",
        json={
            "status": "waiting-on-vendor",
            "reason": "vendor has not replied",
            "actor_session_id": actor,
        },
    )

    assert changed.status_code == 200
    assert changed.json()["status"] == "waiting-on-vendor"

    listed = client.get("/statuses")

    assert listed.status_code == 200
    statuses = listed.json()
    assert len(statuses) == 11
    assert [s["name"] for s in statuses[:10]] == [
        "blocked",
        "needs-help",
        "planning",
        "implementing-plan",
        "diagnosing-ticket",
        "needs-clarification",
        "ready-for-pr",
        "merged",
        "tested-in-cloud",
        "done",
    ]
    assert all(s["is_builtin"] is True for s in statuses[:10])
    assert statuses[10] == {"name": "waiting-on-vendor", "is_builtin": False}

    second_ticket = create_ticket("Review pending")
    changed_again = client.post(
        f"/tickets/{second_ticket}/status",
        json={
            "status": "awaiting-review",
            "reason": "PR is up",
            "actor_session_id": actor,
        },
    )
    assert changed_again.status_code == 200

    relisted = client.get("/statuses")

    assert relisted.status_code == 200
    tail = relisted.json()[10:]
    assert tail == [
        {"name": "awaiting-review", "is_builtin": False},
        {"name": "waiting-on-vendor", "is_builtin": False},
    ]


def test_setting_same_status_again_writes_no_timeline_entry(client):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": actor})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    first = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": actor},
    )
    second = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "still planning", "actor_session_id": actor},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "planning"
    status_changes = [e for e in body["timeline"] if e["kind"] == "status_change"]
    assert len(status_changes) == 1
