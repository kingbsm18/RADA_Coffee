"""Strong-alert notifications (rule R12): decide what to send and deliver it.

Single module for both the decision and the delivery channel(s); do not
re-introduce a separate infra/notifier.py unless a second channel needs it.
TODO: implement.
"""

"""Strong-alert notification policy (business rule R12).

The notification decision uses the café's historical daily anomaly
baseline. Anomalies are always stored; this module only decides whether
a strong notification should be delivered.

No email, SMS or push provider is hard-coded. The caller injects a sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.engine.noise_baseline import (
    NoisePolicy,
    NotifyDecision,
    compute_baseline,
    should_notify,
)
from app.models.alert import Alert
from app.models.org_site import Site
from app.models.site_settings import SiteSettings
from app.models.summary import DailySummary


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    """Minimal information sent to a notification provider."""

    alert_id: str
    site_id: str
    category: str
    detected_at: datetime
    quantity: int
    estimated_loss: str
    currency: str
    message: str


class NotificationSender(Protocol):
    """Interface implemented by email, SMS or push notification adapters."""

    async def send(self, payload: NotificationPayload) -> None:
        """Deliver a notification to the configured recipients."""
        ...


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """Decision and delivery status."""

    decision: NotifyDecision
    sent: bool
    payload: NotificationPayload | None = None


class NotificationConfigurationError(Exception):
    """Raised when notification configuration is invalid."""


def _business_day_bounds(
    target_date: date,
    timezone_name: str,
    start_hour: int,
) -> tuple[datetime, datetime]:
    """Return UTC bounds for a site's local business day."""

    if not 0 <= start_hour <= 23:
        raise ValueError("start_hour must be between 0 and 23")

    zone = ZoneInfo(timezone_name)

    local_start = datetime.combine(
        target_date,
        time(hour=start_hour),
        tzinfo=zone,
    )
    local_end = datetime.combine(
        target_date + timedelta(days=1),
        time(hour=start_hour),
        tzinfo=zone,
    )

    return (
        local_start.astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
    )


def evaluate_strong_notification(
    db: Session,
    alert: Alert,
    *,
    policy: NoisePolicy | None = None,
    history_days: int = 30,
) -> NotifyDecision:
    """Evaluate R12 for the alert's site and category.

    The baseline uses completed DailySummary records from previous
    business days. Missing summary days are not silently treated as zero.
    """

    if history_days < 1:
        raise ValueError("history_days must be at least 1")

    if alert.status != "anomaly":
        baseline = compute_baseline([], policy)
        return should_notify(0, baseline)

    site = db.query(Site).filter(Site.id == alert.site_id).one_or_none()

    if site is None:
        raise NotificationConfigurationError(
            f"Site {alert.site_id!r} does not exist"
        )

    settings = (
        db.query(SiteSettings)
        .filter(SiteSettings.site_id == alert.site_id)
        .one_or_none()
    )

    if settings is not None and not settings.alerts_enabled:
        baseline = compute_baseline([], policy)
        return should_notify(0, baseline)

    local_detected_at = alert.detected_at.astimezone(
        ZoneInfo(site.timezone_name)
    )

    business_date = local_detected_at.date()
    if settings is not None and local_detected_at.hour < settings.business_day_start:
        business_date -= timedelta(days=1)

    start_date = business_date - timedelta(days=history_days)

    history_rows = (
        db.query(DailySummary.summary_date, DailySummary.anomaly_units)
        .filter(
            DailySummary.site_id == alert.site_id,
            DailySummary.category == alert.category,
            DailySummary.summary_date >= start_date,
            DailySummary.summary_date < business_date,
        )
        .order_by(DailySummary.summary_date.asc())
        .all()
    )

    daily_counts = [int(row.anomaly_units) for row in history_rows]
    baseline = compute_baseline(daily_counts, policy)

    day_start, day_end = _business_day_bounds(
        business_date,
        site.timezone_name,
        settings.business_day_start if settings is not None else 0,
    )

    current_count = (
        db.query(Alert)
        .filter(
            Alert.site_id == alert.site_id,
            Alert.category == alert.category,
            Alert.status == "anomaly",
            Alert.detected_at >= day_start,
            Alert.detected_at < day_end,
        )
        .with_entities(Alert.quantity)
        .all()
    )

    total_anomalies = sum(int(row.quantity) for row in current_count)

    return should_notify(total_anomalies, baseline)


def build_notification_payload(alert: Alert) -> NotificationPayload:
    """Build a neutral, non-accusatory notification message."""

    message = (
        f"Écart à vérifier : {alert.quantity} unité(s) détectée(s) "
        f"sans vente POS correspondante dans la catégorie "
        f"{alert.category}. Perte estimée : "
        f"{alert.estimated_loss} {alert.currency}. "
        "Une vérification humaine est nécessaire."
    )

    return NotificationPayload(
        alert_id=str(alert.id),
        site_id=alert.site_id,
        category=alert.category,
        detected_at=alert.detected_at,
        quantity=alert.quantity,
        estimated_loss=str(alert.estimated_loss),
        currency=alert.currency,
        message=message,
    )


async def send_strong_notification(
    db: Session,
    alert: Alert,
    sender: NotificationSender,
    *,
    policy: NoisePolicy | None = None,
) -> NotificationResult:
    """Send a notification only when the R12 baseline is exceeded.

    The sender is injected by the application. This function does not
    create a new alert and does not change the alert's status.
    """

    decision = evaluate_strong_notification(
        db,
        alert,
        policy=policy,
    )

    if not decision.notify:
        return NotificationResult(
            decision=decision,
            sent=False,
        )

    payload = build_notification_payload(alert)
    await sender.send(payload)

    return NotificationResult(
        decision=decision,
        sent=True,
        payload=payload,
    )
