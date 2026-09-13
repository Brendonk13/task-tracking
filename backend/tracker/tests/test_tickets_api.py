import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def test_create_ticket_then_get_returns_title_description_and_default_priority_none(
    client,
):
    session = register_session(client)

    created = client.post(
        "/tickets",
        json={
            "title": "Fix login",
            "description": "Users get 500",
            "actor_session_id": session["session_id"],
        },
    )

    assert created.status_code == 201
    ticket_id = created.json()["id"]

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == ticket_id
    assert body["title"] == "Fix login"
    assert body["description"] == "Users get 500"
    assert body["priority"] == "none"


def test_create_ticket_with_unknown_actor_is_rejected_with_400(client):
    response = client.post(
        "/tickets",
        json={
            "title": "Fix login",
            "description": "Users get 500",
            "actor_session_id": "not-registered",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown actor"}


def test_human_is_an_accepted_actor(client):
    response = client.post(
        "/tickets",
        json={
            "title": "Fix login",
            "description": "Users get 500",
            "actor_session_id": "human",
        },
    )

    assert response.status_code == 201


def test_create_ticket_with_project_and_labels_returns_them_as_tags(client):
    session = register_session(client)

    created = client.post(
        "/tickets",
        json={
            "title": "Fix login",
            "project": "avantos",
            "labels": ["infra", "ai"],
            "actor_session_id": session["session_id"],
        },
    )

    assert created.status_code == 201
    created_body = created.json()
    assert created_body["project"] == "avantos"
    assert created_body["labels"] == ["ai", "infra"]

    fetched = client.get(f"/tickets/{created_body['id']}")

    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["project"] == "avantos"
    assert fetched_body["labels"] == ["ai", "infra"]


def test_patch_ticket_updates_fields_and_records_field_change_in_timeline(client):
    session_id = "c2e8a4f6-1b3d-4d97-8e5c-6a0f2d9b4c13"
    session = register_session(client, session_id=session_id)
    name = session["name"]

    created = client.post(
        "/tickets",
        json={"title": "Fix login", "actor_session_id": session_id},
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    patched = client.patch(
        f"/tickets/{ticket_id}",
        json={"priority": "urgent", "actor_session_id": session_id},
    )

    assert patched.status_code == 200
    assert patched.json()["priority"] == "urgent"

    fetched = client.get(f"/tickets/{ticket_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["priority"] == "urgent"

    timeline = body["timeline"]
    assert isinstance(timeline, list)
    assert len(timeline) == 1
    entry = timeline[0]
    assert entry["kind"] == "field_change"
    assert entry["body"] == f"{name} changed priority from none to urgent"
    assert entry["actor"]["name"] == name
    assert entry["actor"]["session_id"] == session_id
    assert entry["from_status"] is None
    assert entry["to_status"] is None
    assert entry["reason"] is None
