"""Sessions: naming them, and creating the ones this app starts itself.

A session registered through the API describes a process that already exists. A
managed session is the opposite: the row has to exist before the process does, so a
human watching the sessions page never sees a ``claude`` running with nothing to
explain it, and so the crash of a run still leaves the session behind to be found.
"""

import uuid

from django.conf import settings
from django.utils import timezone

from tracker import models
from tracker.services import names

MAX_NAME_ATTEMPTS = 100


def unused_name() -> str:
    """A generated name no session holds yet.

    Names are unique so people can say them out loud; the generator draws at random, so
    collisions are ordinary and are simply redrawn rather than being an error.
    """
    for _ in range(MAX_NAME_ATTEMPTS):
        name = names.generate_name()
        if not models.Session.objects.filter(name=name).exists():
            return name
    raise RuntimeError("could not generate a unique session name")


def create_managed_session(
    *,
    purpose: models.SessionPurpose | str,
    directory: str,
    model: str,
    effort: str,
    ticket: models.Ticket | None = None,
    cron_run: models.CronRun | None = None,
) -> models.Session:
    """Write the row for a session we are about to start, already marked ``running``.

    The id is drawn here rather than read back out of the process, for two reasons: it
    has to be passed to ``claude --session-id`` so the transcript is resumable later
    with ``claude --resume <id>``, and the row cannot be written first if the id only
    arrives afterwards.
    """
    return models.Session.objects.create(
        session_id=str(uuid.uuid4()),
        name=unused_name(),
        directory=directory,
        purpose=purpose,
        model=model,
        effort=effort,
        status=models.SessionStatus.RUNNING,
        ticket=ticket,
        cron_run=cron_run,
    )


def finish_session(
    session: models.Session, *, last_message: str, summary: str = ""
) -> models.Session:
    """Close a managed session out once the process it describes has ended.

    A row written before the process cannot close itself, so the caller that waited on
    the run says how it went. ``last_message`` is what the run itself said, kept
    verbatim because the sessions page shows it the same way it shows a manual
    session's own last message; ``result_summary`` is the run's own verdict, for
    readers who want the answer without opening the artefact.
    """
    session.status = models.SessionStatus.FINISHED
    session.finished_at = timezone.now()
    session.last_message = last_message
    session.last_message_at = session.finished_at
    session.result_summary = summary
    session.save()
    return session


def fail_session(
    session: models.Session, *, last_message: str, summary: str = ""
) -> models.Session:
    """Close a managed session out when the process it describes died.

    A row left reading ``running`` after its process is gone is a ghost on the sessions
    page that nothing will ever clear, so a dead run is recorded as plainly as a
    finished one. ``last_message`` is whatever the run managed to say — often its exit
    message on stderr, sometimes nothing at all — kept verbatim, because that sentence
    is the only evidence a human has of what went wrong.
    """
    session.status = models.SessionStatus.FAILED
    session.finished_at = timezone.now()
    session.last_message = last_message
    session.last_message_at = session.finished_at
    session.result_summary = summary
    session.save()
    return session


def remaining_session_budget(run: models.CronRun) -> int:
    """How many more sessions this cron pass may still start (§2).

    The cron is unattended and every managed session is a paid headless ``claude``, so a
    morning that imports a whole backlog and finds a week of review comments must not
    become a dozen concurrent processes and the day's budget gone in one pass. The
    allowance belongs to the run, not to any one step: an allowance kept per step would
    let the real worst case be a multiple of the number the setting names, and grow
    again with every step added later. It is counted against the sessions already linked
    to this run rather than tracked by the caller, so briefs, PR triage and whatever
    comes next all draw from the one ceiling without having to know about each other.
    """
    spent = models.Session.objects.filter(cron_run=run).count()
    return max(settings.CRON_MAX_SESSIONS_PER_RUN - spent, 0)
