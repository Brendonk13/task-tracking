from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import actors

router = Router(tags=["tickets"])


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


@router.get("/{int:ticket_id}", response=schemas.TicketDetail)
def get_ticket(request, ticket_id: int):
    return get_object_or_404(models.Ticket, id=ticket_id)
