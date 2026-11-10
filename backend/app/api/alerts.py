from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import pagination, require_aware
from app.database import get_db
from app.models.alert import ALERT_STATUSES, Alert
from app.models.org_site import Site, User
from app.schemas.alerts import (
    AlertGroupOut,
    AlertOut,
    AlertPage,
    AlertReviewIn,
    AlertSummaryOut,
    AlertTotalsOut,
    BulkReviewIn,
    BulkReviewOut,
    Priority,
)
from app.security import get_current_user, get_site_for_user
from app.services import alert_service
from app.services.notification import notify_alert_updated

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertPage)
def list_alerts(
    site_id: str,
    status_filter: str | None = None,
    category: str | None = None,
    priority: Priority | None = None,
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
        strong=None if priority is None else priority == "high",
        since=require_aware(since, "since"),
        until=require_aware(until, "until"),
        limit=limit,
        offset=offset,
    )
    return AlertPage(items=[AlertOut.model_validate(a) for a in items], total=total)


# Declared before "/{alert_id}" so that "summary" is not parsed as an id.
@router.get("/summary", response_model=AlertSummaryOut)
def summary(
    site_id: str | None = None,
    from_day: date | None = None,
    to_day: date | None = None,
    category: str | None = None,
    priority: Priority | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertSummaryOut:
    """R11 dashboard view: anomalies grouped by site, day, category and priority.

    Without ``site_id``, every site of the user's organization is included. Nothing here
    asks for a decision: unreviewed anomalies simply stay ``open`` in their group.
    """
    if site_id:
        sites = [get_site_for_user(db, user, site_id)]
    else:
        sites = list(
            db.execute(select(Site).where(Site.org_id == user.org_id).order_by(Site.id)).scalars()
        )
    try:
        groups = alert_service.summarize_alerts(
            db, sites, from_day=from_day, to_day=to_day, category=category, priority=priority
        )
    except alert_service.AlertError as exc:
        raise HTTPException(422, str(exc)) from None

    by_status: dict[str, int] = {}
    for group in groups:
        for name, count in group.by_status.items():
            by_status[name] = by_status.get(name, 0) + count
    totals = AlertTotalsOut(
        count=sum(g.count for g in groups),
        by_status=by_status,
        loss_detected=sum((g.loss_detected_est for g in groups), Decimal("0.00")),
        loss_confirmed=sum((g.loss_confirmed for g in groups), Decimal("0.00")),
    )
    return AlertSummaryOut(
        groups=[AlertGroupOut.model_validate(g) for g in groups], totals=totals
    )


@router.post("/review", response_model=BulkReviewOut)
def review_many(
    payload: BulkReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BulkReviewOut:
    """Optionally qualify a whole group at once (R11). All or nothing."""
    alerts = list(db.execute(select(Alert).where(Alert.id.in_(payload.alert_ids))).scalars())
    visible_sites = set(
        db.execute(select(Site.id).where(Site.org_id == user.org_id)).scalars()
    )
    # Unknown ids and other organizations' alerts look the same: 404, and nothing is changed.
    if len(alerts) != len(payload.alert_ids) or any(a.site_id not in visible_sites for a in alerts):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    try:
        done = alert_service.bulk_review(db, alerts, status=payload.status, user=user, note=payload.note)
    except alert_service.AlertNotReviewable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    for alert in done:
        notify_alert_updated(alert)
    return BulkReviewOut(updated=len(done), alert_ids=[a.id for a in done])


def _load(db: Session, user: User, alert_id: uuid.UUID) -> Alert:
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
    """Optional human decision (R11). Nothing requires it: unreviewed alerts simply stay open."""
    alert = _load(db, user, alert_id)
    try:
        alert = alert_service.review_alert(db, alert, status=payload.status, user=user, note=payload.note)
    except alert_service.AlertNotReviewable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    notify_alert_updated(alert)
    return alert
