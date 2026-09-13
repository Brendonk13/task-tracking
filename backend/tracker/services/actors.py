"""Resolve ``actor_session_id`` on mutating ticket endpoints (section 1 "Actor", A1)."""

from ninja.errors import HttpError

from tracker import models

HUMAN = "human"


def actor_view(actor_session_id: str) -> dict:
    """The A1 ``Actor`` sub-schema, read live from the Session row.

    Raises ``Session.DoesNotExist`` when no such session is registered.
    """
    if actor_session_id == HUMAN:
        return {"session_id": HUMAN, "name": HUMAN, "directory": None}
    session = models.Session.objects.get(session_id=actor_session_id)
    return {
        "session_id": session.session_id,
        "name": session.name,
        "directory": session.directory,
    }


def require_actor(actor_session_id: str) -> dict:
    """Validate an actor on a mutating endpoint and return its ``Actor`` view.

    Raises ``HttpError(400, "unknown actor")`` when no such session is registered.
    """
    try:
        return actor_view(actor_session_id)
    except models.Session.DoesNotExist:
        raise HttpError(400, "unknown actor")
