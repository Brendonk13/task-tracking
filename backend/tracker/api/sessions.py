from typing import List

from django.db.models import F
from ninja import Router

from tracker import models, schemas
from tracker.services import names

router = Router(tags=["sessions"])

MAX_NAME_ATTEMPTS = 100


def _unused_name() -> str:
    for _ in range(MAX_NAME_ATTEMPTS):
        name = names.generate_name()
        if not models.Session.objects.filter(name=name).exists():
            return name
    raise RuntimeError("could not generate a unique session name")


@router.put("/{session_id}", response=schemas.Session)
def register_session(request, session_id: str, payload: schemas.SessionIn):
    """Idempotent upsert (A10). ``name`` is generated once, on first registration."""
    session = models.Session.objects.filter(session_id=session_id).first()
    if session is None:
        return models.Session.objects.create(
            session_id=session_id, name=_unused_name(), **payload.dict()
        )
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(session, field, value)  # omitted keys kept, explicit null clears
    session.save()
    return session


@router.get("", response=List[schemas.Session])
def list_sessions(request):
    return models.Session.objects.order_by(
        F("last_message_at").desc(nulls_last=True), "-created_at"
    )
