import pytest

from tracker.tests.conftest import register_session

pytestmark = pytest.mark.django_db


def make_ticket(client, actor: str, title: str = "Ticket") -> dict:
    response = client.post("/tickets", json={"title": title, "actor_session_id": actor})
    assert response.status_code == 201, response.content
    return response.json()


def make_task(client, actor: str, ticket_id: int, title: str = "Task", **extra) -> dict:
    response = client.post(
        f"/tickets/{ticket_id}/tasks",
        json={"title": title, "actor_session_id": actor, **extra},
    )
    assert response.status_code == 201, response.content
    return response.json()


def set_state(client, actor: str, task_id: int, state: str, reason: str | None = None) -> dict:
    body = {"state": state, "actor_session_id": actor}
    if reason is not None:
        body["reason"] = reason
    response = client.post(f"/tasks/{task_id}/state", json=body)
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def actor(client) -> str:
    return register_session(client)["session_id"]


@pytest.fixture
def actor_name(client, actor) -> str:
    return client.get("/sessions").json()[0]["name"]


@pytest.fixture
def ticket(client, actor) -> dict:
    return make_ticket(client, actor)


# ---- create / read ----


def test_a_new_ticket_has_no_tasks(ticket):
    assert ticket["tasks"] == []


def test_create_task_returns_201_with_task_detail(client, actor, ticket):
    task = make_task(client, actor, ticket["id"], title="  Write the migration  ", description="Add the column")

    assert task["ticket_id"] == ticket["id"]
    assert task["title"] == "Write the migration"
    assert task["description"] == "Add the column"
    assert task["state"] == "todo"
    assert task["depends_on"] == []
    assert task["blocked_by"] == []
    assert task["history"] == []
    assert set(task) == {
        "id", "ticket_id", "title", "description", "state", "depends_on", "blocked_by",
        "created_at", "updated_at", "history",
    }


def test_tasks_appear_on_the_ticket_detail_oldest_first_without_history(client, actor, ticket):
    first = make_task(client, actor, ticket["id"], title="First")
    second = make_task(client, actor, ticket["id"], title="Second")

    body = client.get(f"/tickets/{ticket['id']}").json()

    assert [t["id"] for t in body["tasks"]] == [first["id"], second["id"]]
    assert "history" not in body["tasks"][0]
    assert body["tasks"][0]["title"] == "First"


def test_list_tasks_matches_the_ticket_detail(client, actor, ticket):
    make_task(client, actor, ticket["id"], title="First")
    make_task(client, actor, ticket["id"], title="Second")
    other = make_ticket(client, actor)
    make_task(client, actor, other["id"], title="Elsewhere")

    response = client.get(f"/tickets/{ticket['id']}/tasks")

    assert response.status_code == 200
    assert response.json() == client.get(f"/tickets/{ticket['id']}").json()["tasks"]
    assert [t["title"] for t in response.json()] == ["First", "Second"]


def test_list_tasks_for_an_unknown_ticket_is_404(client):
    assert client.get("/tickets/9999/tasks").status_code == 404


def test_get_task_returns_the_detail(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    response = client.get(f"/tasks/{task['id']}")

    assert response.status_code == 200
    assert response.json() == task


def test_get_unknown_task_is_404(client):
    assert client.get("/tasks/9999").status_code == 404


def test_create_task_requires_a_non_empty_title(client, actor, ticket):
    response = client.post(
        f"/tickets/{ticket['id']}/tasks", json={"title": "   ", "actor_session_id": actor}
    )

    assert response.status_code == 422


def test_create_task_checks_422_then_404_then_400(client, actor):
    assert client.post("/tickets/9999/tasks", json={"actor_session_id": actor}).status_code == 422
    assert client.post(
        "/tickets/9999/tasks", json={"title": "x", "actor_session_id": "nope"}
    ).status_code == 404
    ticket = make_ticket(client, actor)
    response = client.post(
        f"/tickets/{ticket['id']}/tasks", json={"title": "x", "actor_session_id": "nope"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "unknown actor"}


def test_creating_a_task_bumps_the_ticket_updated_at(client, actor, ticket):
    make_task(client, actor, ticket["id"])

    assert client.get(f"/tickets/{ticket['id']}").json()["updated_at"] > ticket["updated_at"]


# ---- state ----


def test_state_change_writes_a_history_entry_with_reason(client, actor, actor_name, ticket):
    task = make_task(client, actor, ticket["id"])

    body = set_state(client, actor, task["id"], "in_progress", reason="Starting now")

    assert body["state"] == "in_progress"
    assert len(body["history"]) == 1
    entry = body["history"][0]
    assert entry["kind"] == "state_change"
    assert entry["body"] == f"{actor_name} changed state from todo to in_progress"
    assert entry["from_state"] == "todo"
    assert entry["to_state"] == "in_progress"
    assert entry["reason"] == "Starting now"
    assert entry["actor"]["session_id"] == actor
    assert entry["actor"]["name"] == actor_name


def test_state_change_reason_is_optional_and_blank_becomes_null(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    body = set_state(client, actor, task["id"], "done", reason="   ")

    assert body["history"][0]["reason"] is None


def test_same_state_again_is_a_no_op(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])
    set_state(client, actor, task["id"], "done")

    body = set_state(client, actor, task["id"], "done")

    assert len(body["history"]) == 1


def test_unknown_state_is_422(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    response = client.post(
        f"/tasks/{task['id']}/state", json={"state": "finished", "actor_session_id": actor}
    )

    assert response.status_code == 422


def test_human_can_change_task_state(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    body = set_state(client, "human", task["id"], "cancelled")

    assert body["history"][0]["body"] == "human changed state from todo to cancelled"
    assert body["history"][0]["actor"] == {"session_id": "human", "name": "human", "directory": None}


def test_history_is_oldest_first(client, actor, actor_name, ticket):
    task = make_task(client, actor, ticket["id"])
    set_state(client, actor, task["id"], "in_progress")
    set_state(client, actor, task["id"], "done")

    history = client.get(f"/tasks/{task['id']}").json()["history"]

    assert [e["to_state"] for e in history] == ["in_progress", "done"]


def test_state_change_checks_404_then_400(client, actor, ticket):
    assert client.post("/tasks/9999/state", json={"state": "done", "actor_session_id": "nope"}).status_code == 404
    task = make_task(client, actor, ticket["id"])
    response = client.post(f"/tasks/{task['id']}/state", json={"state": "done", "actor_session_id": "nope"})
    assert response.status_code == 400
    assert response.json() == {"detail": "unknown actor"}


def test_state_change_bumps_the_ticket_updated_at(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])
    before = client.get(f"/tickets/{ticket['id']}").json()["updated_at"]

    set_state(client, actor, task["id"], "done")

    assert client.get(f"/tickets/{ticket['id']}").json()["updated_at"] > before


# ---- patch ----


def test_patch_title_and_description_write_one_field_change_each(client, actor, actor_name, ticket):
    task = make_task(client, actor, ticket["id"], title="Old")

    response = client.patch(
        f"/tasks/{task['id']}",
        json={"title": "New", "description": "More detail", "actor_session_id": actor},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New"
    assert body["description"] == "More detail"
    assert [e["kind"] for e in body["history"]] == ["field_change", "field_change"]
    assert body["history"][0]["body"] == f"{actor_name} changed title from Old to New"
    assert body["history"][1]["body"] == f"{actor_name} changed description"
    assert body["history"][0]["from_state"] is None
    assert body["history"][0]["reason"] is None


def test_patch_that_changes_nothing_writes_nothing(client, actor, ticket):
    task = make_task(client, actor, ticket["id"], title="Same")

    body = client.patch(
        f"/tasks/{task['id']}", json={"title": "Same", "actor_session_id": actor}
    ).json()

    assert body["history"] == []


def test_patch_rejects_null_on_every_field(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    for field in ("title", "description", "depends_on"):
        response = client.patch(
            f"/tasks/{task['id']}", json={field: None, "actor_session_id": actor}
        )
        assert response.status_code == 422, field


# ---- dependencies (the DAG) ----


def test_create_with_depends_on_links_and_blocks(client, actor, ticket):
    migration = make_task(client, actor, ticket["id"], title="Write the migration")

    api = make_task(client, actor, ticket["id"], title="Expose it", depends_on=[migration["id"]])

    assert api["depends_on"] == [migration["id"]]
    assert api["blocked_by"] == [migration["id"]]


def test_blocked_by_drops_finished_dependencies(client, actor, ticket):
    a = make_task(client, actor, ticket["id"], title="A")
    b = make_task(client, actor, ticket["id"], title="B")
    c = make_task(client, actor, ticket["id"], title="C", depends_on=[a["id"], b["id"]])
    assert c["blocked_by"] == [a["id"], b["id"]]

    set_state(client, actor, a["id"], "done")
    assert client.get(f"/tasks/{c['id']}").json()["blocked_by"] == [b["id"]]

    set_state(client, actor, b["id"], "cancelled")
    refetched = client.get(f"/tasks/{c['id']}").json()
    assert refetched["blocked_by"] == []
    assert refetched["depends_on"] == [a["id"], b["id"]]


def test_depends_on_is_deduplicated_and_sorted(client, actor, ticket):
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"])

    c = make_task(client, actor, ticket["id"], depends_on=[b["id"], a["id"], b["id"]])

    assert c["depends_on"] == [a["id"], b["id"]]


def test_patch_depends_on_replaces_the_list_and_writes_one_field_change(client, actor, actor_name, ticket):
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"])
    c = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    body = client.patch(
        f"/tasks/{c['id']}", json={"depends_on": [b["id"]], "actor_session_id": actor}
    ).json()

    assert body["depends_on"] == [b["id"]]
    assert len(body["history"]) == 1
    assert body["history"][0]["body"] == (
        f"{actor_name} changed depends_on from {a['id']} to {b['id']}"
    )


def test_patch_depends_on_empty_list_clears_it(client, actor, actor_name, ticket):
    a = make_task(client, actor, ticket["id"])
    c = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    body = client.patch(
        f"/tasks/{c['id']}", json={"depends_on": [], "actor_session_id": actor}
    ).json()

    assert body["depends_on"] == []
    assert body["history"][0]["body"] == f"{actor_name} changed depends_on from {a['id']} to (none)"


def test_setting_the_same_dependencies_again_is_a_no_op(client, actor, ticket):
    a = make_task(client, actor, ticket["id"])
    c = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    body = client.patch(
        f"/tasks/{c['id']}", json={"depends_on": [a["id"]], "actor_session_id": actor}
    ).json()

    assert body["history"] == []


def test_dependency_must_exist(client, actor, ticket):
    response = client.post(
        f"/tickets/{ticket['id']}/tasks",
        json={"title": "x", "depends_on": [9999], "actor_session_id": actor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown dependency"}


def test_dependency_must_be_on_the_same_ticket(client, actor, ticket):
    other = make_ticket(client, actor)
    elsewhere = make_task(client, actor, other["id"])

    response = client.post(
        f"/tickets/{ticket['id']}/tasks",
        json={"title": "x", "depends_on": [elsewhere["id"]], "actor_session_id": actor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unknown dependency"}


def test_a_task_cannot_depend_on_itself(client, actor, ticket):
    task = make_task(client, actor, ticket["id"])

    response = client.patch(
        f"/tasks/{task['id']}", json={"depends_on": [task["id"]], "actor_session_id": actor}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "a task cannot depend on itself"}


def test_a_direct_cycle_is_rejected(client, actor, ticket):
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    response = client.patch(
        f"/tasks/{a['id']}", json={"depends_on": [b["id"]], "actor_session_id": actor}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "dependencies would form a cycle"}
    assert client.get(f"/tasks/{a['id']}").json()["depends_on"] == []


def test_a_transitive_cycle_is_rejected(client, actor, ticket):
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"], depends_on=[a["id"]])
    c = make_task(client, actor, ticket["id"], depends_on=[b["id"]])

    response = client.patch(
        f"/tasks/{a['id']}", json={"depends_on": [c["id"]], "actor_session_id": actor}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "dependencies would form a cycle"}


def test_replacing_edges_may_reverse_a_dependency(client, actor, ticket):
    # b -> a today. Flipping to a -> b in one PATCH on a is a cycle (b still points at a),
    # but clearing b first and then pointing a at b is fine.
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    client.patch(f"/tasks/{b['id']}", json={"depends_on": [], "actor_session_id": actor})
    response = client.patch(
        f"/tasks/{a['id']}", json={"depends_on": [b["id"]], "actor_session_id": actor}
    )

    assert response.status_code == 200
    assert response.json()["depends_on"] == [b["id"]]


def test_a_diamond_is_not_a_cycle(client, actor, ticket):
    a = make_task(client, actor, ticket["id"])
    b = make_task(client, actor, ticket["id"], depends_on=[a["id"]])
    c = make_task(client, actor, ticket["id"], depends_on=[a["id"]])

    d = make_task(client, actor, ticket["id"], depends_on=[b["id"], c["id"]])

    assert d["depends_on"] == [b["id"], c["id"]]


def test_actor_is_checked_before_dependencies(client, actor, ticket):
    response = client.post(
        f"/tickets/{ticket['id']}/tasks",
        json={"title": "x", "depends_on": [9999], "actor_session_id": "nope"},
    )

    assert response.json() == {"detail": "unknown actor"}


def test_deleting_a_ticket_removes_its_tasks(client, actor, ticket):
    from tracker import models

    a = make_task(client, actor, ticket["id"])
    make_task(client, actor, ticket["id"], depends_on=[a["id"]])
    set_state(client, actor, a["id"], "done")

    models.Ticket.objects.get(id=ticket["id"]).delete()

    assert not models.Task.objects.exists()
    assert not models.TaskDependency.objects.exists()
    assert not models.TaskHistoryEntry.objects.exists()
