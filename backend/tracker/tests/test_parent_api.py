import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def make_ticket(client, actor: str, title: str = "Ticket", **extra) -> dict:
    response = client.post(
        "/tickets", json={"title": title, "actor_session_id": actor, **extra}
    )
    assert response.status_code == 201, response.content
    return response.json()


@pytest.fixture
def actor(client) -> str:
    return register_session(client)["session_id"]


def test_new_ticket_has_no_parent_and_no_children(client, actor):
    ticket = make_ticket(client, actor)

    assert ticket["parent_id"] is None
    assert ticket["parent"] is None
    assert ticket["children"] == []


def test_create_with_parent_id_links_both_directions(client, actor):
    parent = make_ticket(client, actor, title="Ship auth")

    child = make_ticket(client, actor, title="Write the migration", parent_id=parent["id"])

    assert child["parent_id"] == parent["id"]
    assert child["parent"] == {"id": parent["id"], "title": "Ship auth"}

    refetched = client.get(f"/tickets/{parent['id']}").json()
    assert [c["id"] for c in refetched["children"]] == [child["id"]]
    assert refetched["children"][0]["title"] == "Write the migration"


def test_children_are_oldest_first(client, actor):
    parent = make_ticket(client, actor)
    first = make_ticket(client, actor, title="First", parent_id=parent["id"])
    second = make_ticket(client, actor, title="Second", parent_id=parent["id"])

    body = client.get(f"/tickets/{parent['id']}").json()

    assert [c["id"] for c in body["children"]] == [first["id"], second["id"]]


def test_parent_filter_lists_only_that_parents_children(client, actor):
    parent = make_ticket(client, actor)
    child = make_ticket(client, actor, parent_id=parent["id"])
    unrelated = make_ticket(client, actor)

    response = client.get(f"/tickets?parent={parent['id']}")

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert ids == [child["id"]]
    assert unrelated["id"] not in ids


def test_parent_filter_with_unknown_id_returns_an_empty_list(client, actor):
    make_ticket(client, actor)

    response = client.get("/tickets?parent=9999")

    assert response.status_code == 200
    assert response.json() == []


def test_patch_sets_the_parent_and_writes_one_field_change(client, actor):
    parent = make_ticket(client, actor, title="Ship auth")
    child = make_ticket(client, actor, title="Write the migration")

    response = client.patch(
        f"/tickets/{child['id']}",
        json={"parent_id": parent["id"], "actor_session_id": actor},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["parent_id"] == parent["id"]
    entries = [e for e in body["timeline"] if e["kind"] == "field_change"]
    assert len(entries) == 1
    name = client.get("/sessions").json()[0]["name"]
    assert entries[0]["body"] == f"{name} changed parent_id from (none) to {parent['id']}"


def test_patch_clears_the_parent_with_an_explicit_null(client, actor):
    parent = make_ticket(client, actor)
    child = make_ticket(client, actor, parent_id=parent["id"])

    response = client.patch(
        f"/tickets/{child['id']}", json={"parent_id": None, "actor_session_id": actor}
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] is None
    assert client.get(f"/tickets/{parent['id']}").json()["children"] == []


def test_patch_that_omits_parent_id_leaves_it_alone(client, actor):
    parent = make_ticket(client, actor)
    child = make_ticket(client, actor, parent_id=parent["id"])

    response = client.patch(
        f"/tickets/{child['id']}", json={"priority": "high", "actor_session_id": actor}
    )

    assert response.json()["parent_id"] == parent["id"]


def test_setting_the_same_parent_again_is_a_no_op(client, actor):
    parent = make_ticket(client, actor)
    child = make_ticket(client, actor, parent_id=parent["id"])

    response = client.patch(
        f"/tickets/{child['id']}",
        json={"parent_id": parent["id"], "actor_session_id": actor},
    )

    assert response.status_code == 200
    assert response.json()["timeline"] == []


def test_unknown_parent_id_is_rejected_with_400(client, actor):
    response = client.post(
        "/tickets", json={"title": "Orphan", "parent_id": 9999, "actor_session_id": actor}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown parent"}


def test_a_ticket_cannot_be_its_own_parent(client, actor):
    ticket = make_ticket(client, actor)

    response = client.patch(
        f"/tickets/{ticket['id']}",
        json={"parent_id": ticket["id"], "actor_session_id": actor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "a ticket cannot be its own parent"}


def test_the_hierarchy_is_one_level_deep(client, actor):
    parent = make_ticket(client, actor)
    child = make_ticket(client, actor, parent_id=parent["id"])

    response = client.post(
        "/tickets",
        json={"title": "Grandchild", "parent_id": child["id"], "actor_session_id": actor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "a sub-ticket cannot have sub-tickets"}


def test_a_ticket_with_children_cannot_become_a_sub_ticket(client, actor):
    parent = make_ticket(client, actor)
    make_ticket(client, actor, parent_id=parent["id"])
    other = make_ticket(client, actor)

    response = client.patch(
        f"/tickets/{parent['id']}",
        json={"parent_id": other["id"], "actor_session_id": actor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "a ticket with sub-tickets cannot become one"}


def test_actor_is_checked_before_the_parent(client):
    response = client.post(
        "/tickets",
        json={"title": "Orphan", "parent_id": 9999, "actor_session_id": "not-registered"},
    )

    assert response.json() == {"detail": "unknown actor"}


def test_a_missing_ticket_is_404_before_the_parent_check(client, actor):
    response = client.patch(
        "/tickets/9999", json={"parent_id": 9999, "actor_session_id": actor}
    )

    assert response.status_code == 404
