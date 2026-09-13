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
    session, _created = models.Session.objects.update_or_create(
        session_id=session_id,
        defaults=payload.dict(exclude_unset=True),
        create_defaults={"name": _unused_name(), **payload.dict()},
    )
    return session


@router.get("", response=List[schemas.Session])
def list_sessions(request):
    return models.Session.objects.order_by(
        F("last_message_at").desc(nulls_last=True), "-created_at"
    )
