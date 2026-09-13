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


def _fallback_view(actor_session_id: str) -> dict:
    """``Actor`` for a timeline entry whose Session row no longer exists.

    ``TimelineEntry.actor_session_id`` is a plain string, not a foreign key, so
    deleting a Session must not break rendering the tickets it touched.
    """
    return {"session_id": actor_session_id, "name": actor_session_id, "directory": None}


def actor_view(actor_session_id: str) -> dict:
    """The A1 ``Actor`` sub-schema, read live from the Session row.

    Falls back to ``_fallback_view`` when no such session is registered; use
    ``require_actor`` when a missing session must be an error.
    """
    if actor_session_id == HUMAN:
        return HUMAN_ACTOR
    session = models.Session.objects.filter(session_id=actor_session_id).first()
    return _view(session) if session is not None else _fallback_view(actor_session_id)


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
        sid = entry.actor_session_id
        if sid == HUMAN:
            entry.actor = HUMAN_ACTOR
        else:
            entry.actor = by_id.get(sid) or _fallback_view(sid)


def require_actor(actor_session_id: str) -> dict:
    """Validate an actor on a mutating endpoint and return its ``Actor`` view.

    Raises ``HttpError(400, "unknown actor")`` when no such session is registered.
    """
    if actor_session_id == HUMAN:
        return HUMAN_ACTOR
    session = models.Session.objects.filter(session_id=actor_session_id).first()
    if session is None:
        raise HttpError(400, "unknown actor")
    return _view(session)
