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
