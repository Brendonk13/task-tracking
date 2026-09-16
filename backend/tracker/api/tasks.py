from ninja import Router

from tracker import models, schemas
from tracker.services import actors, changes
from tracker.services import tasks as task_service

router = Router(tags=["tasks"])


def _task_and_actor(task_id: int, actor_session_id: str) -> tuple[models.Task, dict]:
    """Load the task and validate the actor, in A3 order: 404 before 400."""
    task = task_service.detail(task_id)
    return task, actors.require_actor(actor_session_id)


@router.get("/{int:task_id}", response=schemas.TaskDetail)
def get_task(request, task_id: int):
    return task_service.detail(task_id)


@router.patch("/{int:task_id}", response=schemas.TaskDetail)
def patch_task(request, task_id: int, payload: schemas.TaskPatch):
    task, actor = _task_and_actor(task_id, payload.actor_session_id)
    if payload.depends_on is not None:
        task_service.validated_depends_on(task.ticket_id, payload.depends_on, task_id)

    current = {
        "title": task.title,
        "description": task.description,
        "depends_on": sorted(dep.id for dep in task.depends_on.all()),
    }
    changed = False
    for field, new in payload.dict(exclude_unset=True, exclude={"actor_session_id"}).items():
        old = current[field]
        if old == new:
            continue
        changed = True
        if field == "depends_on":
            task.depends_on.set(new)
        else:
            setattr(task, field, new)
        task_service.record(
            task,
            models.TaskHistoryKind.FIELD_CHANGE,
            payload.actor_session_id,
            changes.field_change_body(actor["name"], field, old, new),
        )

    if changed:
        task_service.touch(task)
    return task_service.detail(task.id)


@router.post("/{int:task_id}/state", response=schemas.TaskDetail)
def set_state(request, task_id: int, payload: schemas.TaskStateIn):
    task, actor = _task_and_actor(task_id, payload.actor_session_id)
    from_state = task.state
    if from_state == payload.state:
        return task  # no-op: same state, nothing written
    task.state = payload.state
    task_service.touch(task)
    task_service.record(
        task,
        models.TaskHistoryKind.STATE_CHANGE,
        payload.actor_session_id,
        f"{actor['name']} changed state from {from_state} to {payload.state}",
        from_state=from_state,
        to_state=payload.state,
        reason=payload.reason,
    )
    return task_service.detail(task.id)
