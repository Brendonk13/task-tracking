from typing import List

from django.db import IntegrityError, transaction
from django.db.models import F
from ninja import Router
from ninja.errors import HttpError

from tracker import models, schemas
from tracker.services import actors, names

router = Router(tags=["sessions"])

MAX_NAME_ATTEMPTS = 100
MAX_CREATE_ATTEMPTS = 3


def _unused_name() -> str:
    for _ in range(MAX_NAME_ATTEMPTS):
        name = names.generate_name()
        if not models.Session.objects.filter(name=name).exists():
            return name
    raise RuntimeError("could not generate a unique session name")


@router.put("/{session_id}", response=schemas.Session)
def register_session(request, session_id: str, payload: schemas.SessionIn):
    """Idempotent upsert (A10). ``name`` is generated once, on first registration."""
    if session_id == actors.HUMAN:
        raise HttpError(422, f"session_id {actors.HUMAN!r} is reserved")
    if payload.ticket_id is not None:
        if not models.Ticket.objects.filter(id=payload.ticket_id).exists():
            raise HttpError(400, "unknown ticket")
    for attempt in range(MAX_CREATE_ATTEMPTS):
        try:
            with transaction.atomic():
                # update_or_create absorbs the race where two first PUTs for the same
                # session_id interleave: the loser's INSERT fails and it updates instead.
                session, _created = models.Session.objects.update_or_create(
                    session_id=session_id,
                    # Omitted keys kept, explicit null clears (A10).
                    defaults=payload.dict(exclude_unset=True),
                    # ``name`` is a callable so it is only drawn when actually creating.
                    create_defaults={**payload.dict(), "name": _unused_name},
                )
            return session
        except IntegrityError:
            # Two sessions drew the same (unique) name at once; redraw and retry.
            if attempt == MAX_CREATE_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


@router.get("", response=List[schemas.Session])
def list_sessions(request):
    return models.Session.objects.order_by(
        F("last_message_at").desc(nulls_last=True), "-created_at"
    )
