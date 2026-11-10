"""Alert creation (idempotent, amounts frozen) and manager review (R10, R11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.alert import Alert
from app.models.audit import record_audit
from app.models.detection import Detection
from app.models.org_site import User

REVIEW_STATUSES = ("confirmed", "false_alarm")
_REVIEWABLE_FROM = ("open", "confirmed", "false_alarm")  # auto_resolved is final (R13)


class AlertError(Exception):
    pass


class AlertNotReviewable(AlertError):
    pass


def create_alert(
    db: Session,
    *,
    detection: Detection,
    missing_qty: int,
    loss_est: Decimal,
    loss_min: Decimal,
    loss_max: Decimal,
    subtype: str | None = None,
    strong: bool = False,
) -> tuple[Alert, bool]:
    """Create the alert of an anomalous detection. Returns ``(alert, created)``.

    Idempotent: a second call for the same detection returns the existing alert
    unchanged (the loss amounts stay frozen at their first values).
    """
    if not 0 < missing_qty <= detection.count:
        raise AlertError("missing_qty must be between 1 and the detection count")
    if not (Decimal(0) <= loss_min <= loss_est <= loss_max):
        raise AlertError("loss amounts must satisfy 0 <= min <= estimate <= max")

    existing = db.execute(
        select(Alert).where(Alert.detection_id == detection.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    alert = Alert(
        site_id=detection.site_id,
        detection_id=detection.id,
        category=detection.category,
        subtype=subtype,
        missing_qty=missing_qty,
        loss_est=loss_est,
        loss_min=loss_min,
        loss_max=loss_max,
        strong=strong,
    )
    db.add(alert)
    detection.state = "anomaly"
    db.commit()
    return alert, True


def review_alert(
    db: Session, alert: Alert, *, status: str, user: User, note: str | None = None
) -> Alert:
    """Optional human decision (R11): ``confirmed`` or ``false_alarm``. Audited.

    Never required: an unreviewed alert stays ``open`` and is never confirmed or dismissed automatically.
    """
    if status not in REVIEW_STATUSES:
        raise AlertError(f"invalid review status: {status!r}")
    if alert.status not in _REVIEWABLE_FROM:
        raise AlertNotReviewable(f"alert in status {alert.status!r} cannot be reviewed")

    previous = alert.status
    alert.status = status
    alert.review_note = note
    alert.reviewed_by = user.id
    alert.resolved_at = utcnow()

    detection = db.get(Detection, alert.detection_id)
    if detection is not None:
        detection.state = status

    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="alert.review",
        site_id=alert.site_id,
        target_type="alert",
        target_id=str(alert.id),
        detail={"from": previous, "to": status},
    )
    db.commit()
    return alert


def query_alerts(
    db: Session,
    *,
    site_id: str,
    status: str | None = None,
    category: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Alert], int]:
    conditions = [Alert.site_id == site_id]
    if status:
        conditions.append(Alert.status == status)
    if category:
        conditions.append(Alert.category == category)
    if since:
        conditions.append(Alert.created_at >= since)
    if until:
        conditions.append(Alert.created_at < until)
    total = db.execute(select(func.count()).select_from(Alert).where(*conditions)).scalar_one()
    rows = db.execute(
        select(Alert)
        .where(*conditions)
        .order_by(Alert.created_at.desc(), Alert.id)
        .limit(limit)
        .offset(offset)
    ).scalars()
    return list(rows), total


def get_alert(db: Session, alert_id: uuid.UUID, site_id: str) -> Alert | None:
    alert = db.get(Alert, alert_id)
    return alert if alert is not None and alert.site_id == site_id else None
