from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import pagination, require_aware
from app.database import get_db
from app.models.alert import ALERT_STATUSES
from app.models.org_site import User
from app.schemas.alerts import AlertOut, AlertPage, AlertReviewIn
from app.security import get_current_user, get_site_for_user
from app.services import alert_service
from app.services.notification import notify_alert_updated

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertPage)
def list_alerts(
    site_id: str,
    status_filter: str | None = None,
    category: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertPage:
    get_site_for_user(db, user, site_id)
    if status_filter is not None and status_filter not in ALERT_STATUSES:
        raise HTTPException(422, "unknown status")
    limit, offset = page
    items, total = alert_service.query_alerts(
        db,
        site_id=site_id,
        status=status_filter,
        category=category,
        since=require_aware(since, "since"),
        until=require_aware(until, "until"),
        limit=limit,
        offset=offset,
    )
    return AlertPage(items=[AlertOut.model_validate(a) for a in items], total=total)


def _load(db: Session, user: User, alert_id: uuid.UUID):
    from app.models.alert import Alert

    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    get_site_for_user(db, user, alert.site_id)  # 404 if it belongs to another organization
    return alert


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(
    alert_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _load(db, user, alert_id)


@router.patch("/{alert_id}", response_model=AlertOut)
def review_alert(
    alert_id: uuid.UUID,
    payload: AlertReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The manager decides (R11): confirmed or false_alarm."""
    alert = _load(db, user, alert_id)
    try:
        alert = alert_service.review_alert(db, alert, status=payload.status, user=user, note=payload.note)
    except alert_service.AlertNotReviewable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    notify_alert_updated(alert)
    return alert
