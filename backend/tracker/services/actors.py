"""Resolve ``actor_session_id`` on mutating ticket endpoints (section 1 "Actor")."""

from tracker import models

HUMAN = "human"


def resolve_actor(actor_session_id: str) -> models.Session | None:
    """Return the registered Session, or ``None`` for the reserved ``human`` actor."""
    if actor_session_id == HUMAN:
        return None
    return models.Session.objects.get(session_id=actor_session_id)
