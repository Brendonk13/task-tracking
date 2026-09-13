from typing import List

from ninja import Router

from tracker import models, schemas
from tracker.services import names

router = Router(tags=["sessions"])


@router.put("/{session_id}", response=schemas.Session)
def register_session(request, session_id: str, payload: schemas.SessionIn):
    session, _created = models.Session.objects.update_or_create(
        session_id=session_id,
        defaults=payload.dict(exclude_unset=True),
        create_defaults={"name": names.generate_name(), **payload.dict()},
    )
    return session


@router.get("", response=List[schemas.Session])
def list_sessions(request):
    return models.Session.objects.all()
