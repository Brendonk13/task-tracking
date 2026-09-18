from typing import List

from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.responses import Status

from tracker import models, schemas
from tracker.services import crons

router = Router(tags=["crons"])


@router.post("/run", response={202: schemas.CronRun})
def start_run(request):
    """Record the run here, then let a detached worker do it (§4 C5.1).

    A cron pass talks to Linear, GitHub and Claude Code and takes minutes, which is far
    longer than a request should hold and longer than the autoreloading web process can
    promise to live. So the answer is 202 with a run that is already ``running``: the
    work has been accepted and started elsewhere, and ``GET /crons/summary`` is how the
    caller follows it.
    """
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
