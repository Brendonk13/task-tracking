from ninja import Router

from tracker import models, schemas
from tracker.services import names

router = Router(tags=["sessions"])


@router.put("/{session_id}", response=schemas.Session)
def register_session(request, session_id: str, payload: schemas.SessionIn):
    return models.Session.objects.create(
        session_id=session_id,
        name=names.generate_name(),
        **payload.dict(),
    )
