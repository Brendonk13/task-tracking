from typing import List

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router

from tracker import models, schemas

router = Router(tags=["alerts"])


@router.get("", response=List[schemas.Alert])
def list_alerts(request, dismissed: bool = False):
    """The open alerts, or the whole history when ``dismissed=true``.

    The page is a to-do list (§4 C5.6), so a dismissed alert leaves it by default;
    nothing is deleted, and the flag asks for the full history instead.
    """
    alerts = models.Alert.objects.all()  # Newest first, per Alert.Meta.ordering.
    if not dismissed:
        alerts = alerts.filter(dismissed_at__isnull=True)
    return alerts


# Registered before "/{id}" (A14), or "summary" would be parsed as an id.
@router.get("/summary", response=schemas.AlertsSummary)
def alerts_summary(request):
    """What the nav badge counts: the same rows the default list shows."""
    return {"undismissed_count": models.Alert.objects.filter(dismissed_at__isnull=True).count()}


@router.post("/{int:alert_id}/dismiss", response=schemas.Alert)
def dismiss_alert(request, alert_id: int):
    """Mark an alert handled. A second call is a no-op in the A14 sense: 200, and the
    stored ``dismissed_at`` stays the moment the first call wrote, so the history does
    not lie about when the work was done."""
    alert = get_object_or_404(models.Alert, id=alert_id)
    if alert.dismissed_at is None:
        alert.dismissed_at = timezone.now()
        alert.save(update_fields=["dismissed_at"])
    return alert
