import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def create_ticket(client, actor, title="Fix login"):
    created = client.post("/tickets", json={"title": title, "actor_session_id": actor})
    assert created.status_code == 201
    return created.json()["id"]


def test_set_needs_human_eyes_true_is_reflected_on_ticket_and_timeline(client):
    session_id = "1c7f4a2e-9d3b-4e06-b8a5-3f0c6d9e2b71"
    session = register_session(client, session_id=session_id)
    name = session["name"]
    ticket_id = create_ticket(client, session_id)

    initial = client.get(f"/tickets/{ticket_id}")
    assert initial.status_code == 200
    assert initial.json()["needs_human_eyes"] is False

    initial_list = client.get("/tickets")
    assert initial_list.status_code == 200
    rows = [row for row in initial_list.json() if row["id"] == ticket_id]
    assert len(rows) == 1
    assert rows[0]["needs_human_eyes"] is False

    flagged = client.post(
        f"/tickets/{ticket_id}/needs-human-eyes",
        json={"value": True, "reason": "need a decision on scope", "actor_session_id": session_id},
    )

    assert flagged.status_code == 200
    assert flagged.json()["id"] == ticket_id
    assert flagged.json()["needs_human_eyes"] is True

    after_flag = client.get(f"/tickets/{ticket_id}")

    assert after_flag.status_code == 200
    assert after_flag.json()["needs_human_eyes"] is True
    timeline = after_flag.json()["timeline"]
    assert len(timeline) == 1
    assert timeline[0]["kind"] == "flag_change"
    assert timeline[0]["body"] == f"{name} flagged needs human eyes"
    assert timeline[0]["reason"] == "need a decision on scope"
    assert timeline[0]["from_status"] is None
    assert timeline[0]["to_status"] is None

    cleared = client.post(
        f"/tickets/{ticket_id}/needs-human-eyes",
        json={"value": False, "actor_session_id": session_id},
    )

    assert cleared.status_code == 200
    assert cleared.json()["needs_human_eyes"] is False

    after_clear = client.get(f"/tickets/{ticket_id}")

    assert after_clear.status_code == 200
    timeline = after_clear.json()["timeline"]
    assert len(timeline) == 2
    assert timeline[1]["kind"] == "flag_change"
    assert timeline[1]["body"] == f"{name} cleared needs human eyes"
    assert timeline[1]["reason"] is None

    cleared_again = client.post(
        f"/tickets/{ticket_id}/needs-human-eyes",
        json={"value": False, "actor_session_id": session_id},
    )

    assert cleared_again.status_code == 200
    assert cleared_again.json()["needs_human_eyes"] is False

    after_noop = client.get(f"/tickets/{ticket_id}")

    assert after_noop.status_code == 200
    assert len(after_noop.json()["timeline"]) == 2


def test_list_tickets_filter_needs_human_eyes_true_returns_only_flagged(client):
    session = register_session(client)
    actor = session["session_id"]

    flagged_a = create_ticket(client, actor, "Flagged A")
    unflagged = create_ticket(client, actor, "Unflagged")
    flagged_b = create_ticket(client, actor, "Flagged B")
    for ticket_id in (flagged_a, flagged_b):
        response = client.post(
            f"/tickets/{ticket_id}/needs-human-eyes",
            json={"value": True, "actor_session_id": actor},
        )
        assert response.status_code == 200

    only_flagged = client.get("/tickets?needs_human_eyes=true")

    assert only_flagged.status_code == 200
    assert {row["id"] for row in only_flagged.json()} == {flagged_a, flagged_b}

    only_unflagged = client.get("/tickets?needs_human_eyes=false")

    assert only_unflagged.status_code == 200
    assert {row["id"] for row in only_unflagged.json()} == {unflagged}

    everything = client.get("/tickets")

    assert everything.status_code == 200
    assert {row["id"] for row in everything.json()} == {flagged_a, unflagged, flagged_b}
