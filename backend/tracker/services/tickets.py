"""The writes that change a ticket's state, in one place for every caller.

A ticket is blocked and flagged both by a person clicking in the UI and by the cron
acting on what a session concluded, and the two must be indistinguishable afterwards:
the same timeline entry, the same copy, the same no-op rules. Keeping those writes in
the endpoints would mean the cron either re-implemented them — and drifted — or posted
to its own API over HTTP.
"""

from tracker import models


def record(
    ticket: models.Ticket,
    kind: models.TimelineKind,
    actor_session_id: str,
    body: str,
    **fields,
) -> models.TimelineEntry:
    """Append one timeline entry to the ticket."""
    return models.TimelineEntry.objects.create(
        ticket=ticket, kind=kind, actor_session_id=actor_session_id, body=body, **fields
    )


def change_status(
    ticket: models.Ticket,
    status_name: str,
    actor_session_id: str,
    actor_name: str,
    reason: str | None = None,
) -> models.TimelineEntry | None:
    """Move a ticket to a status and say who moved it and why.

    Asking for the status a ticket already has is a no-op (B3.7): nothing is written and
    ``None`` comes back. That rule is what lets a repeating caller — the cron, which
    triages the same PR again whenever a new comment lands — run over an already blocked
    ticket without adding a second identical entry to its timeline.

    The body reads as a change only when there was something to change from; a ticket
    that had no status at all was set rather than moved.
    """
    from_status = ticket.status.name if ticket.status else None
    if from_status == status_name:
        return None
    status, _created = models.Status.objects.get_or_create(name=status_name)
    ticket.status = status
    ticket.save()
    if from_status is None:
        body = f"{actor_name} set status to {status.name}"
    else:
        body = f"{actor_name} changed status from {from_status} to {status.name}"
    return record(
        ticket,
        models.TimelineKind.STATUS_CHANGE,
        actor_session_id,
        body,
        from_status=from_status,
        to_status=status.name,
        reason=reason,
    )


def set_needs_human_eyes(
    ticket: models.Ticket,
    value: bool,
    actor_session_id: str,
    actor_name: str,
    reason: str | None = None,
) -> models.TimelineEntry | None:
    """Raise or clear the flag that says a person is needed on this ticket (A6).

    Setting the flag to the value it already holds writes nothing and returns ``None``,
    for the same reason as ``change_status``: the flag is a state, not an event, and a
    second caller saying the same thing has changed nothing.
    """
    if ticket.needs_human_eyes == value:
        return None
    ticket.needs_human_eyes = value
    ticket.save()
    verb = "flagged" if value else "cleared"
    return record(
        ticket,
        models.TimelineKind.FLAG_CHANGE,
        actor_session_id,
        f"{actor_name} {verb} needs human eyes",
        reason=reason,
    )
