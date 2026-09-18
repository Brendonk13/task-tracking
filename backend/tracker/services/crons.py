"""The cron: one pass over the work this app watches, recorded as a ``CronRun``.

The command and (later) the API are both thin wrappers over ``start_run`` and
``execute``, so a run behaves the same however it was triggered.
"""

from django.conf import settings
from django.utils import timezone

from tracker import models


def start_run(trigger: models.CronRunTrigger | str, pid: int | None = None) -> models.CronRun:
    """Record a run as ``running`` before any work happens, so a crash is still visible."""
    return models.CronRun.objects.create(trigger=trigger, pid=pid)


# What each step of the pass needs from the environment (§2). A step whose settings
# are not all filled in cannot run, so it is skipped rather than half-done.
STEP_SETTINGS = {
    "import tickets from Linear": ("LINEAR_API_KEY", "LINEAR_ASSIGNEE_EMAIL"),
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


def execute(run: models.CronRun) -> models.CronRun:
    """Do the run's work, then close it out.

    Each step is checked against its config first; an unconfigured step is skipped and
    the pass carries on, so one missing variable never costs the whole run. No step does
    any work yet, so a configured step is a no-op; the run itself is still recorded,
    which is what makes a "nothing to do" cron distinguishable from one that never
    started.
    """
    for step in STEP_SETTINGS:
        missing = missing_settings(step)
        if missing:
            skip_step(run, step, missing)

    run.status = models.CronRunStatus.FINISHED
    run.finished_at = timezone.now()
    run.save()
    return run
