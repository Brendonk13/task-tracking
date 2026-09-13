import re

import pytest

pytestmark = pytest.mark.django_db

NAME_PATTERN = re.compile(r"^[a-z]+-[a-z]+$")


def test_register_session_returns_generated_name_and_stored_fields(client):
    session_id = "3f9c2b7e-5d41-4a8f-9e12-7c0b6a1d8f34"

    response = client.put(
        f"/sessions/{session_id}",
        json={
            "directory": "/home/me/proj",
            "last_message": "please fix the tests",
            "last_message_at": "2026-09-12T10:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["directory"] == "/home/me/proj"
    assert body["last_message"] == "please fix the tests"
    assert body["last_message_at"] == "2026-09-12T10:00:00Z"
    assert isinstance(body["name"], str)
    assert body["name"] != ""
    assert NAME_PATTERN.match(body["name"]), body["name"]
    assert "created_at" in body


def test_register_same_session_twice_keeps_name_and_updates_message(client):
    session_id = "8a1d4e0b-2c6f-4b93-a7e5-0d3f9b2c6e71"
    directory = "/home/me/proj"

    first = client.put(
        f"/sessions/{session_id}",
        json={
            "directory": directory,
            "last_message": "please fix the tests",
            "last_message_at": "2026-09-12T10:00:00Z",
        },
    )
    second = client.put(
        f"/sessions/{session_id}",
        json={
            "directory": directory,
            "last_message": "now run the linter",
            "last_message_at": "2026-09-12T10:05:00Z",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_name = first.json()["name"]
    assert second.json()["name"] == first_name
    assert second.json()["last_message"] == "now run the linter"

    listing = client.get("/sessions")

    assert listing.status_code == 200
    sessions = listing.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["last_message"] == "now run the linter"


def test_generated_names_are_unique_across_sessions(client, seeded_names):
    names = []
    for i in range(50):
        response = client.put(
            f"/sessions/sess-{i:03d}",
            json={"directory": "/home/me/proj"},
        )
        assert response.status_code == 200
        names.append(response.json()["name"])

    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert len(set(names)) == 50, f"duplicate names: {duplicates}"


def test_list_sessions_orders_by_last_message_at_desc(client):
    # Inserted deliberately out of the expected order, with the null-timestamp
    # session registered first so "nulls last" is exercised too.
    registrations = [
        ("sess-no-message", None),
        ("sess-0900", "2026-09-12T09:00:00Z"),
        ("sess-1100", "2026-09-12T11:00:00Z"),
        ("sess-1000", "2026-09-12T10:00:00Z"),
    ]
    for session_id, last_message_at in registrations:
        payload = {"directory": "/home/me/proj"}
        if last_message_at is not None:
            payload["last_message_at"] = last_message_at
        response = client.put(f"/sessions/{session_id}", json=payload)
        assert response.status_code == 200

    listing = client.get("/sessions")

    assert listing.status_code == 200
    assert [s["session_id"] for s in listing.json()] == [
        "sess-1100",
        "sess-1000",
        "sess-0900",
        "sess-no-message",
    ]
