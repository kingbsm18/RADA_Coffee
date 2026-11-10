"""Alert creation (idempotent, amounts frozen) and manager review (R10, R11)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.alert import Alert
from app.models.audit import record_audit
from app.models.detection import Detection
from app.models.org_site import Site, User
from app.services.summary_service import MAX_RANGE_DAYS, day_bounds_utc

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


def priority_of(alert: Alert) -> str:
    """R11 priority: ``high`` for strong alerts (above the R12 noise level), else ``normal``."""
    return "high" if alert.strong else "normal"


def _apply_review(
    db: Session,
    alert: Alert,
    detection: Detection | None,
    *,
    status: str,
    user: User,
    note: str | None,
    bulk: bool,
) -> None:
    detail: dict[str, object] = {"from": alert.status, "to": status}
    if bulk:
        detail["bulk"] = True
    alert.status = status
    alert.review_note = note
    alert.reviewed_by = user.id
    alert.resolved_at = utcnow()  # every human decision is timestamped and attributed (R11)
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
        detail=detail,
    )


def review_alert(
    db: Session, alert: Alert, *, status: str, user: User, note: str | None = None
) -> Alert:
    """Optional human decision (R11): ``confirmed`` or ``false_alarm``. Audited.

    Never required: an unreviewed alert stays ``open`` and is never confirmed or dismissed
    automatically.
    """
    if status not in REVIEW_STATUSES:
        raise AlertError(f"invalid review status: {status!r}")
    if alert.status not in _REVIEWABLE_FROM:
        raise AlertNotReviewable(f"alert in status {alert.status!r} cannot be reviewed")
    _apply_review(
        db, alert, db.get(Detection, alert.detection_id), status=status, user=user, note=note, bulk=False
    )
    db.commit()
    return alert


def bulk_review(
    db: Session, alerts: Sequence[Alert], *, status: str, user: User, note: str | None = None
) -> list[Alert]:
    """Qualify several alerts at once, all or nothing (one transaction)."""
    if status not in REVIEW_STATUSES:
        raise AlertError(f"invalid review status: {status!r}")
    blocked = [str(a.id) for a in alerts if a.status not in _REVIEWABLE_FROM]
    if blocked:
        raise AlertNotReviewable(f"cannot be reviewed: {', '.join(blocked[:10])}")
    detections = {
        d.id: d
        for d in db.execute(
            select(Detection).where(Detection.id.in_([a.detection_id for a in alerts]))
        ).scalars()
    }
    for alert in alerts:
        _apply_review(
            db, alert, detections.get(alert.detection_id), status=status, user=user, note=note, bulk=True
        )
    db.commit()
    return list(alerts)


@dataclass(slots=True)
class AlertGroup:
    site_id: str
    day: date
    category: str
    priority: str
    count: int = 0
    missing_qty: int = 0
    loss_detected_est: Decimal = Decimal("0.00")
    loss_detected_min: Decimal = Decimal("0.00")
    loss_detected_max: Decimal = Decimal("0.00")
    loss_confirmed: Decimal = Decimal("0.00")
    by_status: dict[str, int] = field(default_factory=dict)
    open_alert_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def open_count(self) -> int:
        return self.by_status.get("open", 0)


MAX_GROUP_IDS = 200
_DETECTED = ("open", "confirmed")  # "perte détectée"; false_alarm and auto_resolved are excluded


def summarize_alerts(
    db: Session,
    sites: Sequence[Site],
    *,
    from_day: date | None = None,
    to_day: date | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> list[AlertGroup]:
    """Group anomalies by site, local day (of the served item), category and priority (R11)."""
    groups: dict[tuple[str, date, str, str], AlertGroup] = {}
    for site in sites:
        tz = ZoneInfo(site.timezone)
        end_day = to_day or datetime.now(tz).date()
        start_day = from_day or end_day - timedelta(days=6)
        if start_day > end_day:
            raise AlertError("from_day is after to_day")
        if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
            raise AlertError(f"range too large (max {MAX_RANGE_DAYS} days)")
        start, _ = day_bounds_utc(tz, start_day)
        _, end = day_bounds_utc(tz, end_day)

        conditions = [Alert.site_id == site.id, Detection.timestamp >= start, Detection.timestamp < end]
        if category:
            conditions.append(Alert.category == category)
        if priority:
            conditions.append(Alert.strong.is_(priority == "high"))
        rows = db.execute(
            select(Alert, Detection.timestamp)
            .join(Detection, Detection.id == Alert.detection_id)
            .where(*conditions)
            .order_by(Detection.timestamp, Alert.id)
        )
        for alert, served_at in rows:
            day = served_at.astimezone(tz).date()
            key = (site.id, day, alert.category, priority_of(alert))
            group = groups.setdefault(key, AlertGroup(*key))
            group.count += 1
            group.missing_qty += alert.missing_qty
            group.by_status[alert.status] = group.by_status.get(alert.status, 0) + 1
            if alert.status in _DETECTED:
                group.loss_detected_est += alert.loss_est
                group.loss_detected_min += alert.loss_min
                group.loss_detected_max += alert.loss_max
            if alert.status == "confirmed":
                group.loss_confirmed += alert.loss_est
            if alert.status == "open" and len(group.open_alert_ids) < MAX_GROUP_IDS:
                group.open_alert_ids.append(alert.id)

    return sorted(
        groups.values(),
        key=lambda g: (-g.day.toordinal(), g.site_id, g.category, 0 if g.priority == "high" else 1),
    )


def query_alerts(
    db: Session,
    *,
    site_id: str,
    status: str | None = None,
    category: str | None = None,
    strong: bool | None = None,
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
    if strong is not None:
        conditions.append(Alert.strong.is_(strong))
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
