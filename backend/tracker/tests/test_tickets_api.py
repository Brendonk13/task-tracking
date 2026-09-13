import pytest
from freezegun import freeze_time

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


def test_list_tickets_returns_all_tickets_newest_first_by_default(client):
    session = register_session(client)
    actor = session["session_id"]

    for created_at, title in [
        ("2026-09-12T10:00:00Z", "first ticket"),
        ("2026-09-12T10:01:00Z", "second ticket"),
        ("2026-09-12T10:02:00Z", "third ticket"),
    ]:
        with freeze_time(created_at):
            response = client.post(
                "/tickets", json={"title": title, "actor_session_id": actor}
            )
        assert response.status_code == 201

    listing = client.get("/tickets")

    assert listing.status_code == 200
    rows = listing.json()
    assert isinstance(rows, list)
    assert [row["title"] for row in rows] == [
        "third ticket",
        "second ticket",
        "first ticket",
    ]
    for row in rows:
        assert "id" in row
        assert "title" in row


def test_list_tickets_sort_by_priority_puts_urgent_before_low(client):
    session = register_session(client)
    actor = session["session_id"]

    for priority in ["low", "urgent", "medium"]:
        response = client.post(
            "/tickets",
            json={
                "title": f"{priority} ticket",
                "priority": priority,
                "actor_session_id": actor,
            },
        )
        assert response.status_code == 201

    descending = client.get("/tickets?sort=priority&order=desc")

    assert descending.status_code == 200
    assert [row["priority"] for row in descending.json()] == [
        "urgent",
        "medium",
        "low",
    ]

    ascending = client.get("/tickets?sort=priority&order=asc")

    assert ascending.status_code == 200
    assert [row["priority"] for row in ascending.json()] == [
        "low",
        "medium",
        "urgent",
    ]


def test_ticket_stores_linear_url(client):
    session = register_session(client)
    actor = session["session_id"]
    linear_url = "https://linear.app/avantos/issue/AVA-123/fix-login"

    created = client.post(
        "/tickets",
        json={"title": "Fix login", "linear_url": linear_url, "actor_session_id": actor},
    )

    assert created.status_code == 201
    assert created.json()["linear_url"] == linear_url
    linked_id = created.json()["id"]

    fetched = client.get(f"/tickets/{linked_id}")

    assert fetched.status_code == 200
    assert fetched.json()["linear_url"] == linear_url

    unlinked = client.post(
        "/tickets",
        json={"title": "No Linear issue", "actor_session_id": actor},
    )

    assert unlinked.status_code == 201
    assert unlinked.json()["linear_url"] is None
    unlinked_id = unlinked.json()["id"]

    listing = client.get("/tickets")

    assert listing.status_code == 200
    by_id = {row["id"]: row for row in listing.json()}
    assert by_id[linked_id]["linear_url"] == linear_url
    assert by_id[unlinked_id]["linear_url"] is None


# --- Reviewer follow-ups: contract points not covered by the numbered slices ---


def _create(client, actor, **fields):
    created = client.post("/tickets", json={"title": "Fix login", "actor_session_id": actor, **fields})
    assert created.status_code == 201
    return created.json()


def _detail(client, ticket_id):
    fetched = client.get(f"/tickets/{ticket_id}")
    assert fetched.status_code == 200
    return fetched.json()


def _field_changes(client, ticket_id):
    return [e for e in _detail(client, ticket_id)["timeline"] if e["kind"] == "field_change"]


def test_patch_labels_replaces_set_and_empty_list_clears(client):
    session = register_session(client)
    actor, name = session["session_id"], session["name"]
    ticket_id = _create(client, actor, labels=["infra", "ai"])["id"]

    replaced = client.patch(
        f"/tickets/{ticket_id}", json={"labels": ["ai", "docs"], "actor_session_id": actor}
    )

    assert replaced.status_code == 200
    assert replaced.json()["labels"] == ["ai", "docs"]
    changes = _field_changes(client, ticket_id)
    assert len(changes) == 1
    assert changes[0]["body"] == f"{name} changed labels from ai, infra to ai, docs"

    cleared = client.patch(f"/tickets/{ticket_id}", json={"labels": [], "actor_session_id": actor})

    assert cleared.status_code == 200
    assert cleared.json()["labels"] == []
    changes = _field_changes(client, ticket_id)
    assert len(changes) == 2
    assert changes[1]["body"] == f"{name} changed labels from ai, docs to (none)"


def test_patch_project_and_linear_url_null_clears_them(client):
    session = register_session(client)
    actor, name = session["session_id"], session["name"]
    linear_url = "https://linear.app/avantos/issue/AVA-123/fix-login"
    ticket_id = _create(client, actor, project="avantos", linear_url=linear_url)["id"]

    cleared = client.patch(
        f"/tickets/{ticket_id}",
        json={"project": None, "linear_url": None, "actor_session_id": actor},
    )

    assert cleared.status_code == 200
    assert cleared.json()["project"] is None
    assert cleared.json()["linear_url"] is None
    bodies = {e["body"] for e in _field_changes(client, ticket_id)}
    assert bodies == {
        f"{name} changed project from avantos to (none)",
        f"{name} changed linear_url from {linear_url} to (none)",
    }


def test_patch_description_writes_entry_without_values(client):
    session = register_session(client)
    actor, name = session["session_id"], session["name"]
    ticket_id = _create(client, actor, description="Users get 500")["id"]

    patched = client.patch(
        f"/tickets/{ticket_id}",
        json={"description": "Users get 500 after token refresh", "actor_session_id": actor},
    )

    assert patched.status_code == 200
    assert patched.json()["description"] == "Users get 500 after token refresh"
    changes = _field_changes(client, ticket_id)
    assert len(changes) == 1
    assert changes[0]["body"] == f"{name} changed description"


def test_patch_with_no_changes_writes_nothing_and_multiple_fields_write_one_entry_each(client):
    session = register_session(client)
    actor = session["session_id"]
    ticket_id = _create(client, actor, priority="low")["id"]

    unchanged = client.patch(
        f"/tickets/{ticket_id}",
        json={"title": "Fix login", "priority": "low", "actor_session_id": actor},
    )

    assert unchanged.status_code == 200
    assert _detail(client, ticket_id)["timeline"] == []

    two_fields = client.patch(
        f"/tickets/{ticket_id}",
        json={"title": "Fix login redirect", "priority": "high", "actor_session_id": actor},
    )

    assert two_fields.status_code == 200
    assert two_fields.json()["title"] == "Fix login redirect"
    assert two_fields.json()["priority"] == "high"
    changes = _field_changes(client, ticket_id)
    assert len(changes) == 2
    assert {e["body"].split(" changed ")[1].split(" from ")[0] for e in changes} == {
        "title",
        "priority",
    }


def test_patch_null_on_non_nullable_field_is_422(client):
    session = register_session(client)
    actor = session["session_id"]
    ticket_id = _create(client, actor)["id"]

    null_title = client.patch(f"/tickets/{ticket_id}", json={"title": None, "actor_session_id": actor})

    assert null_title.status_code == 422

    null_priority = client.patch(
        f"/tickets/{ticket_id}", json={"priority": None, "actor_session_id": actor}
    )

    assert null_priority.status_code == 422
    assert _detail(client, ticket_id)["title"] == "Fix login"
    assert _detail(client, ticket_id)["priority"] == "none"


def test_validation_errors_are_422(client):
    session = register_session(client)
    actor = session["session_id"]
    ticket_id = _create(client, actor)["id"]

    empty_reason = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "", "actor_session_id": actor},
    )
    assert empty_reason.status_code == 422

    empty_comment = client.post(
        f"/tickets/{ticket_id}/comments", json={"body": "", "actor_session_id": actor}
    )
    assert empty_comment.status_code == 422

    blank_status = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "  ", "reason": "starting", "actor_session_id": actor},
    )
    assert blank_status.status_code == 422

    assert _detail(client, ticket_id)["timeline"] == []

    padded_status = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "  planning ", "reason": "starting", "actor_session_id": actor},
    )

    assert padded_status.status_code == 200
    assert padded_status.json()["status"] == "planning"


def test_check_order_is_422_then_404_then_400(client):
    missing_ticket_unknown_actor = client.post(
        "/tickets/9999/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": "not-registered"},
    )

    assert missing_ticket_unknown_actor.status_code == 404

    missing_ticket_invalid_body = client.post(
        "/tickets/9999/status",
        json={"status": "planning", "actor_session_id": "not-registered"},
    )

    assert missing_ticket_invalid_body.status_code == 422


def test_updated_at_bumps_on_comment_and_not_on_status_noop(client):
    session = register_session(client)
    actor = session["session_id"]

    with freeze_time("2026-09-12T10:00:00Z"):
        commented_id = _create(client, actor, title="Gets a comment")["id"]
        noop_id = _create(client, actor, title="Gets a status no-op")["id"]
        seeded = client.post(
            f"/tickets/{noop_id}/status",
            json={"status": "planning", "reason": "starting", "actor_session_id": actor},
        )
        assert seeded.status_code == 200

    with freeze_time("2026-09-12T10:01:00Z"):
        commented = client.post(
            f"/tickets/{commented_id}/comments",
            json={"body": "Looking into it.", "actor_session_id": actor},
        )
        assert commented.status_code == 200

    with freeze_time("2026-09-12T10:02:00Z"):
        noop = client.post(
            f"/tickets/{noop_id}/status",
            json={"status": "planning", "reason": "still planning", "actor_session_id": actor},
        )
        assert noop.status_code == 200

    assert _detail(client, commented_id)["updated_at"] == "2026-09-12T10:01:00Z"
    assert _detail(client, noop_id)["updated_at"] == "2026-09-12T10:00:00Z"

    by_activity = client.get("/tickets?sort=updated_at&order=desc")

    assert by_activity.status_code == 200
    assert [row["id"] for row in by_activity.json()] == [commented_id, noop_id]


def test_list_tie_break_on_equal_created_at_follows_order(client):
    session = register_session(client)
    actor = session["session_id"]

    with freeze_time("2026-09-12T10:00:00Z"):
        first = _create(client, actor, title="first")["id"]
        second = _create(client, actor, title="second")["id"]
        third = _create(client, actor, title="third")["id"]

    descending = client.get("/tickets?sort=created_at&order=desc")
    ascending = client.get("/tickets?sort=created_at&order=asc")

    assert descending.status_code == 200
    assert ascending.status_code == 200
    assert [row["id"] for row in descending.json()] == [third, second, first]
    assert [row["id"] for row in ascending.json()] == [first, second, third]


def test_human_actor_on_patch_status_and_flag(client):
    ticket_id = _create(client, "human")["id"]

    patched = client.patch(
        f"/tickets/{ticket_id}", json={"priority": "high", "actor_session_id": "human"}
    )
    status = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": "planning", "reason": "starting", "actor_session_id": "human"},
    )
    flagged = client.post(
        f"/tickets/{ticket_id}/needs-human-eyes",
        json={"value": True, "actor_session_id": "human"},
    )

    assert patched.status_code == 200
    assert status.status_code == 200
    assert flagged.status_code == 200
    timeline = _detail(client, ticket_id)["timeline"]
    assert [e["body"] for e in timeline] == [
        "human changed priority from none to high",
        "human set status to planning",
        "human flagged needs human eyes",
    ]
    assert all(
        e["actor"] == {"session_id": "human", "name": "human", "directory": None}
        for e in timeline
    )


# --- Pins: input normalisation and validation on ticket endpoints ---


def test_labels_are_stripped_and_blank_labels_dropped(client):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post(
        "/tickets",
        json={
            "title": "Fix login",
            "labels": ["", "  ai ", "ai", " infra"],
            "actor_session_id": actor,
        },
    )

    assert created.status_code == 201
    assert created.json()["labels"] == ["ai", "infra"]
    ticket_id = created.json()["id"]
    assert _detail(client, ticket_id)["labels"] == ["ai", "infra"]

    patched = client.patch(
        f"/tickets/{ticket_id}", json={"labels": ["  ", "docs "], "actor_session_id": actor}
    )

    assert patched.status_code == 200
    assert patched.json()["labels"] == ["docs"]
    assert _detail(client, ticket_id)["labels"] == ["docs"]


def test_blank_linear_url_is_null(client):
    session = register_session(client)
    actor = session["session_id"]

    created = client.post(
        "/tickets", json={"title": "Fix login", "linear_url": "", "actor_session_id": actor}
    )

    assert created.status_code == 201
    assert created.json()["linear_url"] is None
    ticket_id = created.json()["id"]

    linked = client.patch(
        f"/tickets/{ticket_id}",
        json={
            "linear_url": "https://linear.app/avantos/issue/AVA-123/fix-login",
            "actor_session_id": actor,
        },
    )
    assert linked.status_code == 200
    assert linked.json()["linear_url"] == "https://linear.app/avantos/issue/AVA-123/fix-login"

    blanked = client.patch(
        f"/tickets/{ticket_id}", json={"linear_url": "   ", "actor_session_id": actor}
    )

    assert blanked.status_code == 200
    assert blanked.json()["linear_url"] is None
    assert _detail(client, ticket_id)["linear_url"] is None


def test_empty_title_is_422(client):
    session = register_session(client)
    actor = session["session_id"]

    empty = client.post("/tickets", json={"title": "", "actor_session_id": actor})

    assert empty.status_code == 422
    assert client.get("/tickets").json() == []

    ticket_id = _create(client, actor)["id"]

    blank = client.patch(f"/tickets/{ticket_id}", json={"title": "   ", "actor_session_id": actor})

    assert blank.status_code == 422
    assert _detail(client, ticket_id)["title"] == "Fix login"
    assert _detail(client, ticket_id)["timeline"] == []


def test_whitespace_only_comment_is_422(client):
    session = register_session(client)
    actor = session["session_id"]
    ticket_id = _create(client, actor)["id"]

    response = client.post(
        f"/tickets/{ticket_id}/comments", json={"body": "   ", "actor_session_id": actor}
    )

    assert response.status_code == 422
    assert _detail(client, ticket_id)["timeline"] == []


def test_status_name_over_100_chars_is_422(client):
    session = register_session(client)
    actor = session["session_id"]
    ticket_id = _create(client, actor)["id"]
    too_long = "s" * 101
    at_limit = "s" * 100

    rejected = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": too_long, "reason": "starting", "actor_session_id": actor},
    )

    assert rejected.status_code == 422
    assert _detail(client, ticket_id)["status"] is None
    assert _detail(client, ticket_id)["timeline"] == []
    assert too_long not in {s["name"] for s in client.get("/statuses").json()}

    accepted = client.post(
        f"/tickets/{ticket_id}/status",
        json={"status": at_limit, "reason": "starting", "actor_session_id": actor},
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == at_limit
    assert _detail(client, ticket_id)["status"] == at_limit
