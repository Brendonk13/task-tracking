from typing import List

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import crons

router = Router(tags=["crons"])


@router.post("/run", response={200: schemas.CronRun, 202: schemas.CronRun})
def start_run(request):
    """Record the run here, then let a detached worker do it (§4 C5.1, C5.2).

    A cron pass talks to Linear, GitHub and Claude Code and takes minutes, which is far
    longer than a request should hold and longer than the autoreloading web process can
    promise to live. So the answer is 202 with a run that is already ``running``: the
    work has been accepted and started elsewhere, and ``GET /crons/summary`` is how the
    caller follows it.

    Only one pass runs at a time. A caller that arrives while one is in flight is not
    doing anything wrong, so it joins that run with 200 and no second worker is started;
    202 is kept for "I started one". Two callers racing both pass the check above, so
    the last word is the ``one_running_cron_run`` constraint: the loser's INSERT fails
    and it joins the winner's run like any other late caller — or, if the winner has
    already finished by then, starts the pass itself, since either way the caller is
    answered with a run that exists.
    """
    # Before asking whether a pass is in flight, discard the ones that only look like
    # it: a run whose worker died without closing its row would otherwise block every
    # later trigger for ever (§4 C5.3).
    crons.reap_stale()
    running = crons.running_run()
    if running is not None:
        return Status(200, running)
    try:
        with transaction.atomic():
            run = crons.start_run(models.CronRunTrigger.API)
    except IntegrityError:
        # The winner of that race may already have finished by the time we look, and a
        # caller cannot follow a run that is not there, so the run is asked for again
        # rather than assumed: join the one still in flight, or, when the race left
        # nothing running, start the pass this caller asked for after all.
        joined = crons.running_run()
        if joined is not None:
            return Status(200, joined)
        run = crons.start_run(models.CronRunTrigger.API)
    crons.spawn_worker(run)
    return Status(202, run)


@router.get("/summary", response=schemas.CronsSummary)
def crons_summary(request):
    return {
        "running": models.CronRun.objects.filter(
            status=models.CronRunStatus.RUNNING
        ).exists(),
        # Newest first, per CronRun.Meta.ordering, so the first row is the latest run.
        "last_run": models.CronRun.objects.first(),
    }


@router.get("/runs", response=List[schemas.CronRun])
def list_runs(request):
    # Newest first, per CronRun.Meta.ordering.
    return models.CronRun.objects.all()


@router.get("/runs/{int:run_id}", response=schemas.CronRun)
def get_run(request, run_id: int):
    return get_object_or_404(models.CronRun, id=run_id)
