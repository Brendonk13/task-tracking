from enum import Enum
from typing import List

from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import actors, tags

router = Router(tags=["tickets"])

PRIORITY_RANK = {
    models.Priority.URGENT: 4,
    models.Priority.HIGH: 3,
    models.Priority.MEDIUM: 2,
    models.Priority.LOW: 1,
    models.Priority.NONE: 0,
}


class SortField(str, Enum):
    created_at = "created_at"
    updated_at = "updated_at"
    priority = "priority"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


def _tickets():
    """Base queryset for every ticket response: no per-row status/tag queries."""
    return models.Ticket.objects.select_related("status").prefetch_related("tags")


def _detail(ticket_id: int) -> models.Ticket:
    """Load one ticket as ``TicketDetail`` needs it: tags, ordered timeline, actors."""
    ticket = get_object_or_404(
        _tickets().prefetch_related(
            Prefetch("timeline", queryset=models.TimelineEntry.objects.order_by("created_at", "id"))
        ),
        id=ticket_id,
    )
    actors.attach_actors(ticket.timeline.all())
    return ticket


def _ticket_and_actor(ticket_id: int, actor_session_id: str) -> tuple[models.Ticket, dict]:
    """Load the ticket and validate the actor, in A3 order: 404 before 400."""
    ticket = get_object_or_404(_tickets(), id=ticket_id)
    return ticket, actors.require_actor(actor_session_id)


def _record(
    ticket: models.Ticket,
    kind: models.TimelineKind,
    actor_session_id: str,
    body: str,
    **fields,
) -> models.TimelineEntry:
    """Append one timeline entry to the ticket."""
    return models.TimelineEntry.objects.create(
        ticket=ticket, kind=kind, actor_session_id=actor_session_id, body=body, **fields
    )


@router.post("", response={201: schemas.TicketDetail})
def create_ticket(request, payload: schemas.TicketCreate):
    actors.require_actor(payload.actor_session_id)
    ticket = models.Ticket.objects.create(
        **payload.dict(exclude={"actor_session_id", "project", "labels"})
    )
    tags.set_tags(ticket, payload.project, payload.labels)
    return Status(201, _detail(ticket.id))


def _render(value) -> str:
    """A5: null/empty renders as ``(none)``; lists comma-joined and sorted."""
    if value is None or value == "" or value == []:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(sorted(value))
    return str(value)


def _field_change_body(actor_name: str, field: str, old, new) -> str:
    if field == "description":
        return f"{actor_name} changed description"
    return f"{actor_name} changed {field} from {_render(old)} to {_render(new)}"


@router.get("/summary", response=schemas.TicketsSummary)
def tickets_summary(request):
    return {
        "needs_human_eyes_count": models.Ticket.objects.filter(
            needs_human_eyes=True
        ).count()
    }


@router.patch("/{int:ticket_id}", response=schemas.TicketDetail)
def patch_ticket(request, ticket_id: int, payload: schemas.TicketPatch):
    ticket, actor = _ticket_and_actor(ticket_id, payload.actor_session_id)

    current = {
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "linear_url": ticket.linear_url,
        "project": tags.project_of(ticket),
        "labels": tags.labels_of(ticket),
    }
    changed_fields = []
    for field, new in payload.dict(exclude_unset=True, exclude={"actor_session_id"}).items():
        if field == "labels":
            new = tags.normalize_labels(new)
        old = current[field]
        if old == new:
            continue
        changed_fields.append(field)
        current[field] = new
        if field not in ("project", "labels"):
            setattr(ticket, field, new)
        _record(
            ticket,
            models.TimelineKind.FIELD_CHANGE,
            payload.actor_session_id,
            _field_change_body(actor["name"], field, old, new),
        )

    if changed_fields:
        if "project" in changed_fields or "labels" in changed_fields:
            tags.set_tags(ticket, current["project"], current["labels"])
        ticket.save()
    return _detail(ticket.id)


@router.get("", response=List[schemas.TicketListItem])
def list_tickets(
    request,
    sort: SortField = SortField.created_at,
    order: SortOrder = SortOrder.desc,
    needs_human_eyes: bool | None = None,
    status: List[str] = Query([]),
):
    queryset = _tickets()
    if needs_human_eyes is not None:
        queryset = queryset.filter(needs_human_eyes=needs_human_eyes)
    if status:
        queryset = queryset.filter(status__name__in=status)  # OR across values
    sort_key = sort.value
    if sort is SortField.priority:
        sort_key = "priority_rank"
        queryset = queryset.annotate(
            priority_rank=Case(
                *(When(priority=p, then=Value(rank)) for p, rank in PRIORITY_RANK.items()),
                output_field=IntegerField(),
            )
        )
    prefix = "-" if order is SortOrder.desc else ""
    keys = dict.fromkeys([sort_key, "created_at", "id"])  # A9 tie-breaks, deduped
    return queryset.order_by(*(f"{prefix}{key}" for key in keys))


@router.post("/{int:ticket_id}/status", response=schemas.TicketDetail)
def set_status(request, ticket_id: int, payload: schemas.StatusChangeIn):
    ticket, actor = _ticket_and_actor(ticket_id, payload.actor_session_id)
    from_status = ticket.status.name if ticket.status else None
    if from_status == payload.status:
        return _detail(ticket.id)  # B3.7 no-op: same status, nothing written
    status, _created = models.Status.objects.get_or_create(name=payload.status)
    ticket.status = status
    ticket.save()
    if from_status is None:
        body = f"{actor['name']} set status to {status.name}"
    else:
        body = f"{actor['name']} changed status from {from_status} to {status.name}"
    _record(
        ticket,
        models.TimelineKind.STATUS_CHANGE,
        payload.actor_session_id,
        body,
        from_status=from_status,
        to_status=status.name,
        reason=payload.reason,
    )
    return _detail(ticket.id)


@router.post("/{int:ticket_id}/comments", response=schemas.TicketDetail)
def add_comment(request, ticket_id: int, payload: schemas.CommentIn):
    ticket, _actor = _ticket_and_actor(ticket_id, payload.actor_session_id)
    _record(ticket, models.TimelineKind.COMMENT, payload.actor_session_id, payload.body)
    ticket.save()  # A8: comments count as activity
    return _detail(ticket.id)


@router.post("/{int:ticket_id}/needs-human-eyes", response=schemas.TicketDetail)
def set_needs_human_eyes(request, ticket_id: int, payload: schemas.NeedsHumanEyesIn):
    ticket, actor = _ticket_and_actor(ticket_id, payload.actor_session_id)
    if ticket.needs_human_eyes == payload.value:
        return _detail(ticket.id)  # A6 no-op: same value, nothing written
    ticket.needs_human_eyes = payload.value
    ticket.save()
    verb = "flagged" if payload.value else "cleared"
    _record(
        ticket,
        models.TimelineKind.FLAG_CHANGE,
        payload.actor_session_id,
        f"{actor['name']} {verb} needs human eyes",
        reason=payload.reason,
    )
    return _detail(ticket.id)


@router.get("/{int:ticket_id}", response=schemas.TicketDetail)
def get_ticket(request, ticket_id: int):
    return _detail(ticket_id)
