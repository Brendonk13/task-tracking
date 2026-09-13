import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def test_first_status_writes_timeline_entry_set_status_with_actor_name_and_reason(
    client,
):
    session_id = "d7b3f9a1-4e6c-4c28-9a5d-2f8e0b6c1d94"
    session = register_session(client, session_id=session_id)
    name = session["name"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": session_id})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    changed = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": session_id},
    )
    assert changed.status_code == 200

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    timeline = fetched.json()["timeline"]
    assert len(timeline) == 1
    entry = timeline[0]
    assert entry["kind"] == "status_change"
    assert entry["body"] == f"{name} set status to planning"
    assert entry["reason"] == "starting"
    assert entry["to_status"] == "planning"
    assert entry["from_status"] is None
    assert entry["actor"]["name"] == name
    assert entry["actor"]["session_id"] == session_id
