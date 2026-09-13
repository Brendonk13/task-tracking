from enum import Enum
from typing import List

from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import actors

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


def _tag(kind: models.TagKind, name: str) -> models.Tag:
    tag, _created = models.Tag.objects.get_or_create(kind=kind, name=name)
    return tag


def _set_tags(ticket: models.Ticket, project: str | None, labels: list[str]) -> None:
    tags = [_tag(models.TagKind.LABEL, name) for name in set(labels)]
    if project is not None:
        tags.append(_tag(models.TagKind.PROJECT, project))
    ticket.tags.set(tags)


@router.post("", response={201: schemas.TicketDetail})
def create_ticket(request, payload: schemas.TicketCreate):
    actors.resolve_actor(payload.actor_session_id)
    ticket = models.Ticket.objects.create(
        **payload.dict(exclude={"actor_session_id", "project", "labels"})
    )
    _set_tags(ticket, payload.project, payload.labels)
    return Status(201, ticket)


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


@router.patch("/{int:ticket_id}", response=schemas.TicketDetail)
def patch_ticket(request, ticket_id: int, payload: schemas.TicketPatch):
    ticket = get_object_or_404(models.Ticket, id=ticket_id)
    actor = actors.resolve_actor(payload.actor_session_id)

    current = {
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "project": schemas.TicketDetail.resolve_project(ticket),
        "labels": schemas.TicketDetail.resolve_labels(ticket),
    }
    changed_fields = []
    for field, new in payload.dict(exclude_unset=True, exclude={"actor_session_id"}).items():
        if field == "labels":
            new = sorted(set(new))
        old = current[field]
        if old == new:
            continue
        changed_fields.append(field)
        current[field] = new
        if field not in ("project", "labels"):
            setattr(ticket, field, new)
        models.TimelineEntry.objects.create(
            ticket=ticket,
            kind=models.TimelineEntry.FIELD_CHANGE,
            actor_session_id=payload.actor_session_id,
            body=_field_change_body(actor["name"], field, old, new),
        )

    if changed_fields:
        if "project" in changed_fields or "labels" in changed_fields:
            _set_tags(ticket, current["project"], current["labels"])
        ticket.save()
    return ticket


@router.get("", response=List[schemas.TicketListItem])
def list_tickets(
    request,
    sort: SortField = SortField.created_at,
    order: SortOrder = SortOrder.desc,
):
    queryset = models.Ticket.objects.all()
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


@router.get("/{int:ticket_id}", response=schemas.TicketDetail)
def get_ticket(request, ticket_id: int):
    return get_object_or_404(models.Ticket, id=ticket_id)
