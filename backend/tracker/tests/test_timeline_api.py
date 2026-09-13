import pytest
from freezegun import freeze_time

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


def test_changing_status_writes_changed_from_to_entry(client):
    session_id = "e1f4c8b2-7a9d-4f61-b3e0-5c2d8a7f9b06"
    session = register_session(client, session_id=session_id)
    name = session["name"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": session_id})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    first = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": session_id},
    )
    assert first.status_code == 200

    second = client.post(
        f"/tickets/{ticket_id}/status",
        json={
            "status": "implementing-plan",
            "reason": "plan approved",
            "actor_session_id": session_id,
        },
    )

    assert second.status_code == 200
    assert second.json()["status"] == "implementing-plan"

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    timeline = fetched.json()["timeline"]
    assert len(timeline) == 2
    entry = timeline[-1]
    assert entry["kind"] == "status_change"
    assert entry["body"] == f"{name} changed status from planning to implementing-plan"
    assert entry["from_status"] == "planning"
    assert entry["to_status"] == "implementing-plan"
    assert entry["reason"] == "plan approved"


def test_add_comment_appears_in_timeline_with_actor_name(client):
    session_id = "f3a9d2c7-5b1e-4a84-9c6f-8e0d4b2a7c15"
    session = register_session(client, session_id=session_id)
    name = session["name"]
    comment = "Investigated: the token refresh races the logout."

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": session_id})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    commented = client.post(
        f"/tickets/{ticket_id}/comments",
        json={"body": comment, "actor_session_id": session_id},
    )

    assert commented.status_code == 200
    assert commented.json()["id"] == ticket_id

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    timeline = fetched.json()["timeline"]
    assert len(timeline) == 1
    entry = timeline[0]
    assert entry["kind"] == "comment"
    assert entry["body"] == comment
    assert entry["actor"]["name"] == name
    assert entry["actor"]["session_id"] == session_id
    assert entry["from_status"] is None
    assert entry["to_status"] is None
    assert entry["reason"] is None

    human_commented = client.post(
        f"/tickets/{ticket_id}/comments",
        json={"body": "Thanks, I will look at the logout flow.", "actor_session_id": "human"},
    )
    assert human_commented.status_code == 200

    refetched = client.get(f"/tickets/{ticket_id}")

    assert refetched.status_code == 200
    timeline = refetched.json()["timeline"]
    assert len(timeline) == 2
    assert timeline[1]["kind"] == "comment"
    assert timeline[1]["body"] == "Thanks, I will look at the logout flow."
    assert timeline[1]["actor"] == {"session_id": "human", "name": "human", "directory": None}


def test_timeline_is_ordered_oldest_first_and_interleaves_comments_and_status_changes(
    client,
):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": actor})
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    with freeze_time("2026-09-12T10:00:00Z"):
        first = client.post(
            f"/tickets/{ticket_id}/comments",
            json={"body": "Starting to look at this.", "actor_session_id": actor},
        )
    with freeze_time("2026-09-12T10:01:00Z"):
        second = client.post(
            f"/tickets/{ticket_id}/status",
            json={"status": "planning", "reason": "scoping the fix", "actor_session_id": actor},
        )
    with freeze_time("2026-09-12T10:02:00Z"):
        third = client.post(
            f"/tickets/{ticket_id}/comments",
            json={"body": "Plan drafted.", "actor_session_id": actor},
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    timeline = fetched.json()["timeline"]
    assert [e["kind"] for e in timeline] == ["comment", "status_change", "comment"]
    assert [e["created_at"] for e in timeline] == [
        "2026-09-12T10:00:00Z",
        "2026-09-12T10:01:00Z",
        "2026-09-12T10:02:00Z",
    ]


def test_timeline_actor_includes_session_id_directory_and_name(client):
    session_id = "0b6e3c9d-8f2a-4d57-a1c4-7e5b9d3f0a28"
    session = register_session(client, session_id=session_id, directory="/home/me/work/api")
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
    assert timeline[0]["actor"] == {
        "session_id": session_id,
        "name": name,
        "directory": "/home/me/work/api",
    }
