"""Sessions: naming them, and opening and closing the ones this app starts itself.

A session registered through the API describes a process that already exists. A
managed session is the opposite: the row has to exist before the process does, so a
human watching the sessions page never sees a ``claude`` running with nothing to
explain it, and so the crash of a run still leaves the session behind to be found.

That also makes closing one this module's job rather than each caller's: a row written
before its process cannot close itself, and a run that dies owes the same writes
whether it was briefing a ticket or triaging a pull request.
"""

import uuid

from django.conf import settings
from django.utils import timezone

from tracker import models
from tracker.integrations.claude_runner import ClaudeResult
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


def failure_reason(result: ClaudeResult) -> str:
    """Why a run died, in the run's own words where it left any.

    A killed session says nothing at all, so the timeout is stated by us; anything else
    is quoted rather than worded ourselves, because the binary is the only thing that
    knows whether it ran out of credit or choked on a flag.
    """
    if result.timed_out:
        return f"timed out after {settings.CLAUDE_SESSION_TIMEOUT_SECONDS}s"
    said = (result.stderr or result.result_text or "").strip()
    exited = f"exited {result.exit_code}"
    return f"{exited}: {said}" if said else exited


def record_failure(
    session: models.Session,
    result: ClaudeResult,
    *,
    message: str,
    ticket: models.Ticket | None = None,
    pull_request: models.PullRequest | None = None,
) -> models.Alert:
    """Close a dead managed session out and leave the one alert that reports it.

    Every managed run this app starts dies the same way and owes the same two writes: the
    session stops claiming to be ``running``, and a ``cron_error`` carries it — so the
    alerts page can name the run and resume its transcript — along with the cron run it
    belonged to and whatever the run was about. That belongs here, beside the creating
    and closing of managed sessions, rather than being written once per kind of run.

    What differs between runs is only what a human is told and what the alert links to,
    so the caller words the ``message`` (it knows whether a brief or a triage failed, and
    which ticket or pull request by name) and names the rows it should be filterable by.
    Nothing is inferred from the failure itself: a run that died produced nothing, so
    nothing derived from its output is written here.
    """
    fail_session(session, last_message=result.stderr or result.result_text)
    return models.Alert.objects.create(
        kind=models.AlertKind.CRON_ERROR,
        ticket=ticket,
        pull_request=pull_request,
        session=session,
        cron_run=session.cron_run,
        message=message,
    )


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
