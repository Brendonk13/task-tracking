from typing import List

from django.shortcuts import get_object_or_404
from ninja import Router

from tracker import models, schemas

router = Router(tags=["crons"])


@router.get("/runs", response=List[schemas.CronRun])
def list_runs(request):
    # Newest first, per CronRun.Meta.ordering.
    return models.CronRun.objects.all()


@router.get("/runs/{int:run_id}", response=schemas.CronRun)
def get_run(request, run_id: int):
    return get_object_or_404(models.CronRun, id=run_id)
