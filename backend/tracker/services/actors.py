"""Resolve ``actor_session_id`` on mutating ticket endpoints (section 1 "Actor")."""

from ninja.errors import HttpError

from tracker import models

HUMAN = "human"


def resolve_actor(actor_session_id: str) -> models.Session | None:
    """Return the registered Session, or ``None`` for the reserved ``human`` actor.

    Raises ``HttpError(400, "unknown actor")`` when no such session is registered.
    """
    if actor_session_id == HUMAN:
        return None
    try:
        return models.Session.objects.get(session_id=actor_session_id)
    except models.Session.DoesNotExist:
        raise HttpError(400, "unknown actor")
