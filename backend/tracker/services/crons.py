"""The cron: one pass over the work this app watches, recorded as a ``CronRun``.

The command and (later) the API are both thin wrappers over ``start_run`` and
``execute``, so a run behaves the same however it was triggered.
"""

from django.utils import timezone

from tracker import models


def start_run(trigger: models.CronRunTrigger | str, pid: int | None = None) -> models.CronRun:
    """Record a run as ``running`` before any work happens, so a crash is still visible."""
    return models.CronRun.objects.create(trigger=trigger, pid=pid)


def execute(run: models.CronRun) -> models.CronRun:
    """Do the run's work, then close it out.

    There are no steps configured yet, so the pass is empty; the run itself is still
    recorded, which is what makes a "nothing to do" cron distinguishable from one that
    never started.
    """
    run.status = models.CronRunStatus.FINISHED
    run.finished_at = timezone.now()
    run.save()
    return run
