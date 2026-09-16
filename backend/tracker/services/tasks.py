"""Tasks: the small pieces a ticket's work is made of, and the DAG between them.

A task belongs to one ticket. ``depends_on`` edges only run between tasks on the same
ticket and may not form a cycle; both rules are enforced here because the tables cannot.
"""

from collections import defaultdict, deque

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from ninja.errors import HttpError

from tracker import models
from tracker.services import actors


def queryset():
    """Base queryset for every task response: ``depends_on`` (with states) prefetched."""
    return models.Task.objects.prefetch_related(
        Prefetch("depends_on", queryset=models.Task.objects.only("id", "state"))
    )


def detail(task_id: int) -> models.Task:
    """Load one task as ``TaskDetail`` needs it: dependencies, history, actors."""
    task = get_object_or_404(
        queryset().prefetch_related(
            Prefetch(
                "history",
                queryset=models.TaskHistoryEntry.objects.order_by("created_at", "id"),
            )
        ),
        id=task_id,
    )
    actors.attach_actors(task.history.all())
    return task


def validated_depends_on(
    ticket_id: int, requested: list[int], task_id: int | None = None
) -> list[int]:
    """Check the dependency ids a task is asking for; return them sorted.

    ``task_id`` is the task being edited, or ``None`` when the task is being created
    (a new task has no dependents yet, so it cannot close a cycle).
    """
    requested = sorted(set(requested))
    if not requested:
        return requested
    if task_id is not None and task_id in requested:
        raise HttpError(400, "a task cannot depend on itself")
    on_ticket = set(
        models.Task.objects.filter(ticket_id=ticket_id).values_list("id", flat=True)
    )
    if not set(requested) <= on_ticket:
        raise HttpError(400, "unknown dependency")
    if task_id is not None and _reaches(ticket_id, requested, task_id, ignore_from=task_id):
        raise HttpError(400, "dependencies would form a cycle")
    return requested


def _reaches(ticket_id: int, sources: list[int], target: int, ignore_from: int) -> bool:
    """Is ``target`` reachable from any of ``sources`` along ``depends_on`` edges?

    Edges out of ``ignore_from`` are skipped: they are the ones being replaced.
    """
    edges: dict[int, list[int]] = defaultdict(list)
    links = models.TaskDependency.objects.filter(task__ticket_id=ticket_id).exclude(
        task_id=ignore_from
    )
    for task_id, depends_on_id in links.values_list("task_id", "depends_on_id"):
        edges[task_id].append(depends_on_id)
    seen = set(sources)
    frontier = deque(sources)
    while frontier:
        node = frontier.popleft()
        if node == target:
            return True
        for nxt in edges[node]:
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return False


def record(
    task: models.Task,
    kind: models.TaskHistoryKind,
    actor_session_id: str,
    body: str,
    **fields,
) -> models.TaskHistoryEntry:
    """Append one history entry to the task."""
    return models.TaskHistoryEntry.objects.create(
        task=task, kind=kind, actor_session_id=actor_session_id, body=body, **fields
    )


def touch(task: models.Task) -> None:
    """A8: task activity is ticket activity; bump both ``updated_at`` columns."""
    task.save()
    task.ticket.save()
