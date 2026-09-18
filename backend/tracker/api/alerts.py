from typing import List

from ninja import Router

from tracker import models, schemas

router = Router(tags=["alerts"])


@router.get("", response=List[schemas.Alert])
def list_alerts(request):
    # Newest first, per Alert.Meta.ordering.
    return models.Alert.objects.all()
