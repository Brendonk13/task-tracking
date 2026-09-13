from typing import List

from django.db.models import F
from ninja import Router

from tracker import models, schemas

router = Router(tags=["statuses"])


@router.get("", response=List[schemas.StatusItem])
def list_statuses(request):
    # A13: built-ins first in canonical order, then customs sorted by name.
    return models.Status.objects.order_by(
        "-is_builtin", F("position").asc(nulls_last=True), "name"
    )
