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
