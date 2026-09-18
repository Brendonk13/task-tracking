"""The cron: one pass over the work this app watches, recorded as a ``CronRun``.

The command and (later) the API are both thin wrappers over ``start_run`` and
``execute``, so a run behaves the same however it was triggered.
"""

from django.conf import settings
from django.utils import timezone

from tracker import models
from tracker.integrations import linear
from tracker.services import tags


def start_run(trigger: models.CronRunTrigger | str, pid: int | None = None) -> models.CronRun:
    """Record a run as ``running`` before any work happens, so a crash is still visible."""
    return models.CronRun.objects.create(trigger=trigger, pid=pid)


# What each step of the pass needs from the environment (§2). A step whose settings
# are not all filled in cannot run, so it is skipped rather than half-done.
IMPORT_TICKETS = "import tickets from Linear"

STEP_SETTINGS = {
    IMPORT_TICKETS: ("LINEAR_API_KEY", "LINEAR_ASSIGNEE_EMAIL"),
}

# Linear grades urgency 1 (most urgent) to 4, with 0 meaning "nobody said".
PRIORITY_BY_LINEAR = {
    0: models.Priority.NONE,
    1: models.Priority.URGENT,
    2: models.Priority.HIGH,
    3: models.Priority.MEDIUM,
    4: models.Priority.LOW,
}


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


def check_new_tickets(run: models.CronRun) -> list[models.Ticket]:
    """Import the Linear issues assigned to us as tickets.

    An import is a birth, not an edit: the ticket arrives already holding these values,
    so no ``field_change`` timeline entry is written for them. There is nobody to
    attribute such a change to, and a reader wants the issue's history from Linear, not
    a replay of the import.
    """
    client = linear.LinearClient(settings.LINEAR_API_KEY)
    issues = client.assigned_active_issues(settings.LINEAR_ASSIGNEE_EMAIL)

    imported = []
    for issue in issues:
        ticket = models.Ticket.objects.create(
            title=issue.title,
            description=issue.description,
            priority=PRIORITY_BY_LINEAR[issue.priority],
            linear_url=issue.url,
            linear_id=issue.id,
            linear_identifier=issue.identifier,
        )
        tags.set_tags(ticket, issue.project, issue.labels)
        imported.append(ticket)
    return imported


# Each step of the pass, in the order it runs.
STEPS = {
    IMPORT_TICKETS: check_new_tickets,
}


def execute(run: models.CronRun) -> models.CronRun:
    """Do the run's work, then close it out.

    Each step is checked against its config first; an unconfigured step is skipped and
    the pass carries on, so one missing variable never costs the whole run. The run itself
    is recorded either way, which is what makes a "nothing to do" cron distinguishable
    from one that never started.
    """
    for step, do_step in STEPS.items():
        missing = missing_settings(step)
        if missing:
            skip_step(run, step, missing)
            continue
        do_step(run)

    run.status = models.CronRunStatus.FINISHED
    run.finished_at = timezone.now()
    run.save()
    return run
