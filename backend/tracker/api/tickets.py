from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import actors

router = Router(tags=["tickets"])


@router.post("", response={201: schemas.TicketDetail})
def create_ticket(request, payload: schemas.TicketCreate):
    actors.resolve_actor(payload.actor_session_id)
    ticket = models.Ticket.objects.create(
        **payload.dict(exclude={"actor_session_id"})
    )
    return Status(201, ticket)


@router.get("/{int:ticket_id}", response=schemas.TicketDetail)
def get_ticket(request, ticket_id: int):
    return get_object_or_404(models.Ticket, id=ticket_id)
