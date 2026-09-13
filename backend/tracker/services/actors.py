"""Resolve ``actor_session_id`` on mutating ticket endpoints (section 1 "Actor", A1)."""

from ninja.errors import HttpError

from tracker import models

HUMAN = "human"


HUMAN_ACTOR = {"session_id": HUMAN, "name": HUMAN, "directory": None}


def _view(session: models.Session) -> dict:
    return {
        "session_id": session.session_id,
        "name": session.name,
        "directory": session.directory,
    }


def actor_view(actor_session_id: str) -> dict:
    """The A1 ``Actor`` sub-schema, read live from the Session row.

    Raises ``Session.DoesNotExist`` when no such session is registered.
    """
    if actor_session_id == HUMAN:
        return HUMAN_ACTOR
    return _view(models.Session.objects.get(session_id=actor_session_id))


def attach_actors(entries) -> None:
    """Set ``entry.actor`` on every timeline entry using a single Session query.

    ``schemas.TimelineEntry`` prefers this pre-resolved attribute and only falls
    back to a per-entry lookup when it is absent.
    """
    entries = list(entries)
    wanted = {e.actor_session_id for e in entries} - {HUMAN}
    by_id = {
        s.session_id: _view(s)
        for s in models.Session.objects.filter(session_id__in=wanted)
    }
    for entry in entries:
        if entry.actor_session_id == HUMAN:
            entry.actor = HUMAN_ACTOR
        elif entry.actor_session_id in by_id:
            entry.actor = by_id[entry.actor_session_id]


def require_actor(actor_session_id: str) -> dict:
    """Validate an actor on a mutating endpoint and return its ``Actor`` view.

    Raises ``HttpError(400, "unknown actor")`` when no such session is registered.
    """
    try:
        return actor_view(actor_session_id)
    except models.Session.DoesNotExist:
        raise HttpError(400, "unknown actor")
