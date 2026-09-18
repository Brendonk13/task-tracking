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


# --- Reviewer follow-ups: A10 merge rule and naive datetimes ---


def test_register_session_put_keeps_omitted_fields_and_clears_explicit_null(client):
    session_id = "5e2a8c4f-1d7b-4b39-a6e0-9c3f7d2b8a51"

    with_message = client.put(
        f"/sessions/{session_id}",
        json={"directory": "/home/me/proj", "last_message": "please fix the tests"},
    )
    assert with_message.status_code == 200
    assert with_message.json()["last_message"] == "please fix the tests"

    directory_only = client.put(f"/sessions/{session_id}", json={"directory": "/home/me/proj"})

    assert directory_only.status_code == 200
    assert directory_only.json()["last_message"] == "please fix the tests"

    explicit_null = client.put(
        f"/sessions/{session_id}",
        json={"directory": "/home/me/proj", "last_message": None},
    )

    assert explicit_null.status_code == 200
    assert explicit_null.json()["last_message"] is None

    listing = client.get("/sessions")

    assert listing.status_code == 200
    assert [s["last_message"] for s in listing.json() if s["session_id"] == session_id] == [None]


def test_naive_last_message_at_is_treated_as_utc(client):
    response = client.put(
        "/sessions/6f3b9d1c-8a2e-4c75-b0d4-1e7a5c9f3b82",
        json={"directory": "/home/me/proj", "last_message_at": "2026-09-12T10:00:00"},
    )

    assert response.status_code == 200
    assert response.json()["last_message_at"] == "2026-09-12T10:00:00Z"


# --- Pin: the reserved actor literal can never be registered as a session ---


def test_reserved_session_id_human_is_rejected(client):
    response = client.put("/sessions/human", json={"directory": "/home/me/proj"})

    assert response.status_code == 422

    listing = client.get("/sessions")

    assert listing.status_code == 200
    assert listing.json() == []


# --- The ticket a session is working on (optional, reported by the session itself) ---

SID = "1b8e4d60-7c39-4f21-a5d8-2e6b0f94c317"


def make_ticket(client, title: str = "Fix login") -> int:
    response = client.post("/tickets", json={"title": title, "actor_session_id": "human"})
    assert response.status_code == 201, response.content
    return response.json()["id"]


def test_session_has_no_ticket_by_default(client):
    response = client.put(f"/sessions/{SID}", json={"directory": "/home/me/proj"})

    assert response.json()["ticket_id"] is None


def test_put_stores_the_ticket_the_session_is_working_on(client):
    ticket_id = make_ticket(client)

    response = client.put(
        f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": ticket_id}
    )

    assert response.status_code == 200
    assert response.json()["ticket_id"] == ticket_id
    assert client.get("/sessions").json()[0]["ticket_id"] == ticket_id


def test_a_later_put_that_omits_ticket_id_keeps_it(client):
    ticket_id = make_ticket(client)
    client.put(f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": ticket_id})

    response = client.put(
        f"/sessions/{SID}", json={"directory": "/home/me/proj", "last_message": "keep going"}
    )

    assert response.json()["ticket_id"] == ticket_id


def test_an_explicit_null_clears_the_ticket(client):
    ticket_id = make_ticket(client)
    client.put(f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": ticket_id})

    response = client.put(
        f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": None}
    )

    assert response.json()["ticket_id"] is None


def test_a_session_can_move_to_another_ticket(client):
    first = make_ticket(client, "First")
    second = make_ticket(client, "Second")
    client.put(f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": first})

    response = client.put(
        f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": second}
    )

    assert response.json()["ticket_id"] == second


def test_unknown_ticket_id_is_rejected_with_400(client):
    response = client.put(
        f"/sessions/{SID}", json={"directory": "/home/me/proj", "ticket_id": 9999}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown ticket"}
    assert client.get("/sessions").json() == []


# --- C5.8: a session a human registered by hand is not a managed one ---


def test_sessions_list_exposes_purpose_model_effort_and_status_and_hand_registered_sessions_are_manual(
    client,
):
    response = client.put(f"/sessions/{SID}", json={"directory": "/home/me/proj"})

    assert response.status_code == 200

    listing = client.get("/sessions")

    assert listing.status_code == 200
    rows = [s for s in listing.json() if s["session_id"] == SID]
    assert len(rows) == 1
    row = rows[0]
    assert row["purpose"] == "manual"
    assert row["model"] is None
    assert row["effort"] is None
    assert row["status"] is None
    assert row["result_summary"] is None
    assert row["finished_at"] is None
