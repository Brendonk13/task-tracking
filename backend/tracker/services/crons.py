"""The cron: one pass over the work this app watches, recorded as a ``CronRun``.

The command and (later) the API are both thin wrappers over ``start_run`` and
``execute``, so a run behaves the same however it was triggered.
"""

import re

from django.conf import settings
from django.utils import timezone

from tracker import models
from tracker.integrations import linear
from tracker.services import briefs, tags


def start_run(trigger: models.CronRunTrigger | str, pid: int | None = None) -> models.CronRun:
    """Record a run as ``running`` before any work happens, so a crash is still visible."""
    return models.CronRun.objects.create(trigger=trigger, pid=pid)


# What each step of the pass needs from the environment (§2). A step whose settings
# are not all filled in cannot run, so it is skipped rather than half-done.
IMPORT_TICKETS = "import tickets from Linear"
WRITE_BRIEFS = "write ticket briefs"

STEP_SETTINGS = {
    IMPORT_TICKETS: ("LINEAR_API_KEY", "LINEAR_ASSIGNEE_EMAIL"),
    WRITE_BRIEFS: ("CLAUDE_BIN", "BRIEFS_DIR", "REPO_DIRS"),
}

# Linear grades urgency 1 (most urgent) to 4, with 0 meaning "nobody said".
PRIORITY_BY_LINEAR = {
    0: models.Priority.NONE,
    1: models.Priority.URGENT,
    2: models.Priority.HIGH,
    3: models.Priority.MEDIUM,
    4: models.Priority.LOW,
}


# A Linear issue URL spells its identifier out after ``/issue/``, e.g.
# https://linear.app/avantos/issue/CON-7/external-handoff-dispatch-drops-the-task-id
LINEAR_ISSUE_URL = re.compile(r"/issue/(?P<identifier>[A-Za-z][A-Za-z0-9]*-\d+)")


def identifier_in_url(url: str | None) -> str | None:
    """The Linear identifier a URL points at, upper-cased, or ``None``.

    People often raise the ticket here first and paste the Linear URL into it, leaving
    ``linear_identifier`` blank. The URL is then the only place the identifier is
    written down, so reading it back out is what lets the import recognise an issue it
    already has a ticket for.
    """
    match = LINEAR_ISSUE_URL.search(url or "")
    return match.group("identifier").upper() if match else None


def missing_settings(step: str) -> list[str]:
    """The names of the settings ``step`` needs that are blank."""
    return [name for name in STEP_SETTINGS[step] if not getattr(settings, name, None)]


def skip_step(run: models.CronRun, step: str, missing: list[str]) -> models.Alert:
    """Record why a step did not run.

    The cron runs unattended, so bad config must not raise and must never fall back to a
    guessed value — it leaves an alert naming the variables a human has to set.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.CRON_ERROR,
        cron_run=run,
        message=f"Skipped {step}: set {', '.join(missing)}.",
    )


def fail_step(run: models.CronRun, step: str, error: Exception) -> models.Alert:
    """Record that a step raised, so the rest of the pass can carry on.

    The cron runs unattended, so an outage at one source — Linear rejecting the key,
    say — must not cost the whole pass. The alert quotes the error rather than
    wording it ourselves, because the sender is the only one who knows what went
    wrong, and a human reading the alerts page needs that sentence to act on it.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.CRON_ERROR,
        cron_run=run,
        message=f"Failed {step}: {error}",
    )


def announce_new_ticket(ticket: models.Ticket) -> models.Alert:
    """Tell a human a ticket was born while nobody was watching.

    The import is the only actor here, so the alerts page is where the news lands. The
    message names the issue the way Linear does — identifier then title — because that
    is what a person recognises it by, and the link carries the ticket itself.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.NEW_TICKET,
        ticket=ticket,
        message=f"Imported {ticket.linear_identifier}: {ticket.title}",
    )


def check_new_tickets(run: models.CronRun) -> list[models.Ticket]:
    """Import the Linear issues assigned to us as tickets.

    An import is a birth, not an edit: the ticket arrives already holding these values,
    so no ``field_change`` timeline entry is written for them. There is nobody to
    attribute such a change to, and a reader wants the issue's history from Linear, not
    a replay of the import.

    Only issues we have never seen before are born here. An issue a human already
    raised a ticket for by hand — recognised by the identifier they pasted in as a
    Linear URL — is adopted instead of duplicated: it gains the issue's ``linear_id``
    and ``linear_identifier``, and keeps everything the human wrote, which they may
    have worded that way on purpose. The cron runs every fifteen
    minutes over the same open issues, so an issue that already has a ticket is left
    untouched — not re-saved with identical values, which would move ``updated_at`` and
    make every pass look like a change.
    """
    client = linear.LinearClient(settings.LINEAR_API_KEY)
    issues = client.assigned_active_issues(settings.LINEAR_ASSIGNEE_EMAIL)

    known = set(models.Ticket.objects.values_list("linear_id", flat=True))
    unlinked = {}
    for ticket in models.Ticket.objects.filter(linear_id__isnull=True):
        identifier = ticket.linear_identifier or identifier_in_url(ticket.linear_url)
        if identifier:
            unlinked.setdefault(identifier.upper(), ticket)

    imported = []
    for issue in issues:
        if issue.id in known:
            continue
        adopted = unlinked.get(issue.identifier.upper())
        if adopted is not None:
            adopted.linear_id = issue.id
            adopted.linear_identifier = issue.identifier
            adopted.save(update_fields=["linear_id", "linear_identifier"])
            continue
        ticket = models.Ticket.objects.create(
            title=issue.title,
            description=issue.description,
            priority=PRIORITY_BY_LINEAR[issue.priority],
            linear_url=issue.url,
            linear_id=issue.id,
            linear_identifier=issue.identifier,
        )
        tags.set_tags(ticket, issue.project, issue.labels)
        announce_new_ticket(ticket)
        imported.append(ticket)
    return imported


# Each step of the pass, in the order it runs.
STEPS = {
    IMPORT_TICKETS: check_new_tickets,
    # Briefs run after the import, so a ticket born in this pass is briefed in it too.
    WRITE_BRIEFS: briefs.write_briefs,
}


def execute(run: models.CronRun) -> models.CronRun:
    """Do the run's work, then close it out.

    Each step is checked against its config first; an unconfigured step is skipped and
    the pass carries on, so one missing variable never costs the whole run. A step that
    raises is isolated the same way: the failure becomes an alert and the next step still
    gets its turn. The run itself is recorded either way, which is what makes a "nothing
    to do" cron distinguishable from one that never started.
    """
    for step, do_step in STEPS.items():
        missing = missing_settings(step)
        if missing:
            skip_step(run, step, missing)
            continue
        try:
            do_step(run)
        except Exception as error:  # any failure here belongs to this step, not the run
            fail_step(run, step, error)

    run.status = models.CronRunStatus.FINISHED
    run.finished_at = timezone.now()
    run.save()
    return run
