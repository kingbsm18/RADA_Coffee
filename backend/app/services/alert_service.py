"""app/services/alert_service.py — TODO: implement (see docs/architecture.md)."""

"""Alert lifecycle and manager review services.

Business rules:
- One alert per detection event.
- Loss estimates are calculated from paid, non-free POS sales
  over the previous 30 days.
- Loss values are frozen when the alert is created.
- A manager can review an open anomaly as confirmed or false_alarm.
- Every manager review is recorded in the audit log.

The service flushes changes but does not commit. Transaction ownership
belongs to the API endpoint or calling application service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.engine.loss import PriceStats, estimate_loss
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.org_site import Site
from app.models.pos_sale import POSSale


AlertReviewValue = Literal["confirmed", "false_alarm"]


class AlertServiceError(Exception):
    """Base exception for alert service operations."""


class AlertNotFoundError(AlertServiceError):
    """Raised when an alert does not exist."""


class AlertAlreadyReviewedError(AlertServiceError):
    """Raised when an alert is no longer open for review."""


class PriceStatisticsUnavailableError(AlertServiceError):
    """Raised when there are no eligible prices to estimate a loss."""


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def get_category_price_stats(
    db: Session,
    site_id: str,
    category: str,
    reference_time: datetime,
) -> PriceStats:
    """Calculate weighted average, minimum and maximum unit prices.

    R10:
    - Only paid sales are included.
    - Free items (0 MAD) are excluded.
    - Voided and refunded sales are excluded.
    - The period is the 30 days before reference_time.
    """

    _require_aware(reference_time, "reference_time")

    period_start = reference_time - timedelta(days=30)

    result = (
        db.query(
            func.sum(POSSale.unit_price * POSSale.quantity),
            func.sum(POSSale.quantity),
            func.min(POSSale.unit_price),
            func.max(POSSale.unit_price),
        )
        .filter(
            POSSale.site_id == site_id,
            POSSale.category == category,
            POSSale.status == "paid",
            POSSale.unit_price > Decimal("0"),
            POSSale.timestamp >= period_start,
            POSSale.timestamp <= reference_time,
        )
        .one()
    )

    total_revenue, total_quantity, minimum, maximum = result

    if not total_quantity or minimum is None or maximum is None:
        raise PriceStatisticsUnavailableError(
            f"No eligible paid POS prices for site={site_id!r}, "
            f"category={category!r}, in the previous 30 days"
        )

    weighted_average = Decimal(total_revenue) / Decimal(total_quantity)

    return PriceStats(
        average=weighted_average,
        minimum=Decimal(minimum),
        maximum=Decimal(maximum),
    )


def create_alert(
    db: Session,
    detection,
    *,
    quantity: int | None = None,
    subtype: str = "missing_sale",
    reference_time: datetime | None = None,
) -> Alert:
    """Create one anomaly alert for a detection event.

    Pass quantity explicitly when only part of a detection event is
    anomalous. Otherwise, the detection's full count is used.

    This function is idempotent for an existing detection_event_id.
    """

    anomaly_quantity = detection.count if quantity is None else quantity

    if isinstance(anomaly_quantity, bool) or not isinstance(
        anomaly_quantity, int
    ):
        raise TypeError("quantity must be an integer")

    if anomaly_quantity <= 0:
        raise ValueError("quantity must be greater than zero")

    if anomaly_quantity > detection.count:
        raise ValueError("quantity cannot exceed detection.count")

    if subtype not in {"missing_sale", "cancelled_after_service"}:
        raise ValueError(f"Unsupported alert subtype: {subtype!r}")

    existing = (
        db.query(Alert)
        .filter(
            Alert.detection_event_id == detection.event_id
        )
        .one_or_none()
    )

    if existing is not None:
        return existing

    now = reference_time or datetime.now(timezone.utc)
    _require_aware(now, "reference_time")
    _require_aware(detection.timestamp, "detection.timestamp")

    site = db.query(Site).filter(Site.id == detection.site_id).one_or_none()

    if site is None:
        raise AlertServiceError(
            f"Site {detection.site_id!r} does not exist"
        )

    prices = get_category_price_stats(
        db=db,
        site_id=detection.site_id,
        category=detection.category,
        reference_time=now,
    )

    loss = estimate_loss(anomaly_quantity, prices)

    alert = Alert(
        detection_event_id=detection.event_id,
        site_id=detection.site_id,
        category=detection.category,
        detected_at=detection.timestamp,
        quantity=anomaly_quantity,
        status="anomaly",
        subtype=subtype,
        estimated_loss=loss.estimated,
        min_estimated_loss=loss.minimum,
        max_estimated_loss=loss.maximum,
        currency=site.currency,
    )

    db.add(alert)
    db.flush()

    db.add(
        AuditLog(
            site_id=detection.site_id,
            actor_id="system",
            actor_type="system",
            entity_type="alert",
            entity_id=str(alert.id),
            action="created",
            details={
                "detection_event_id": detection.event_id,
                "category": detection.category,
                "quantity": anomaly_quantity,
                "subtype": subtype,
                "estimated_loss": str(loss.estimated),
                "currency": site.currency,
            },
        )
    )

    db.flush()
    return alert


def get_alert(
    db: Session,
    alert_id: UUID,
    *,
    site_id: str | None = None,
) -> Alert:
    """Retrieve an alert, optionally scoped to a site."""

    query = db.query(Alert).filter(Alert.id == alert_id)

    if site_id is not None:
        query = query.filter(Alert.site_id == site_id)

    alert = query.one_or_none()

    if alert is None:
        raise AlertNotFoundError(f"Alert {alert_id} not found")

    return alert


def list_alerts(
    db: Session,
    site_id: str,
    *,
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Alert], int]:
    """Return a paginated list of alerts for one site."""

    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")

    if offset < 0:
        raise ValueError("offset cannot be negative")

    query = db.query(Alert).filter(Alert.site_id == site_id)

    if status is not None:
        allowed = {
            "anomaly",
            "confirmed",
            "false_alarm",
            "auto_resolved",
        }
        if status not in allowed:
            raise ValueError(f"Unsupported alert status: {status}")
        query = query.filter(Alert.status == status)

    if category is not None:
        query = query.filter(Alert.category == category)

    total = query.count()

    items = (
        query.order_by(
            Alert.detected_at.desc(),
            Alert.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return items, total


def review_alert(
    db: Session,
    alert_id: UUID,
    *,
    site_id: str,
    actor_id: str,
    status: AlertReviewValue,
    review_note: str | None = None,
    reviewed_at: datetime | None = None,
) -> Alert:
    """Review an open anomaly as confirmed or false_alarm.

    A previously reviewed or automatically resolved alert cannot be
    silently overwritten by another review.
    """

    if status not in {"confirmed", "false_alarm"}:
        raise ValueError(
            "Review status must be 'confirmed' or 'false_alarm'"
        )

    if not actor_id.strip():
        raise ValueError("actor_id cannot be empty")

    if review_note is not None and len(review_note) > 1000:
        raise ValueError("review_note cannot exceed 1000 characters")

    now = reviewed_at or datetime.now(timezone.utc)
    _require_aware(now, "reviewed_at")

    alert = get_alert(db, alert_id, site_id=site_id)

    if alert.status != "anomaly":
        raise AlertAlreadyReviewedError(
            f"Alert {alert_id} cannot be reviewed from status "
            f"{alert.status!r}"
        )

    previous_status = alert.status

    alert.status = status
    alert.reviewed_at = now
    alert.reviewed_by = actor_id
    alert.review_note = review_note

    db.add(
        AuditLog(
            site_id=site_id,
            actor_id=actor_id,
            actor_type="user",
            entity_type="alert",
            entity_id=str(alert.id),
            action=status,
            details={
                "previous_status": previous_status,
                "new_status": status,
                "review_note": review_note,
            },
        )
    )

    db.flush()
    return alert
