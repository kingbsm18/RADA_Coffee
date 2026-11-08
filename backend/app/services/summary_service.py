"""app/services/summary_service.py — TODO: implement (see docs/architecture.md)."""

"""Daily summary aggregation service for RADA Coffee.

The summary is calculated independently for each category and local
business date.

Important:
- POS sales without detections are revenue, not losses.
- Low-confidence detections are not anomalies.
- Auto-resolved anomalies are excluded from the official final anomaly
  and loss totals.
- False alarms are excluded from estimated loss.
- Monetary calculations use Decimal.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.detection import Detection
from app.models.org_site import Site
from app.models.pos_sale import POSSale
from app.models.site_settings import SiteSettings
from app.models.summary import DailySummary


ZERO_MONEY = Decimal("0.00")


class SummaryServiceError(Exception):
    """Base exception for summary operations."""


def business_day_bounds(
    target_date: date,
    timezone_name: str,
    start_hour: int = 0,
) -> tuple[datetime, datetime]:
    """Convert one local business date into UTC start/end timestamps."""

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


def get_site_reporting_configuration(
    db: Session,
    site_id: str,
) -> tuple[Site, SiteSettings | None]:
    """Retrieve the site's timezone and optional business settings."""

    site = db.query(Site).filter(Site.id == site_id).one_or_none()

    if site is None:
        raise SummaryServiceError(f"Site {site_id!r} does not exist")

    settings = (
        db.query(SiteSettings)
        .filter(SiteSettings.site_id == site_id)
        .one_or_none()
    )

    return site, settings


def _get_categories_for_day(
    db: Session,
    site_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> set[str]:
    """Return categories present in POS, detections or alerts."""

    categories: set[str] = set()

    pos_categories = (
        db.query(POSSale.category)
        .filter(
            POSSale.site_id == site_id,
            POSSale.category.is_not(None),
            POSSale.timestamp >= start_utc,
            POSSale.timestamp < end_utc,
        )
        .distinct()
        .all()
    )

    detection_categories = (
        db.query(Detection.category)
        .filter(
            Detection.site_id == site_id,
            Detection.timestamp >= start_utc,
            Detection.timestamp < end_utc,
        )
        .distinct()
        .all()
    )

    alert_categories = (
        db.query(Alert.category)
        .filter(
            Alert.site_id == site_id,
            Alert.detected_at >= start_utc,
            Alert.detected_at < end_utc,
        )
        .distinct()
        .all()
    )

    categories.update(row[0] for row in pos_categories if row[0])
    categories.update(row[0] for row in detection_categories if row[0])
    categories.update(row[0] for row in alert_categories if row[0])

    return categories


def _aggregate_category(
    db: Session,
    site_id: str,
    category: str,
    start_utc: datetime,
    end_utc: datetime,
) -> dict:
    """Calculate the daily metrics for one site/category."""

    pos_result = (
        db.query(
            func.coalesce(func.sum(POSSale.quantity), 0),
            func.coalesce(
                func.sum(POSSale.unit_price * POSSale.quantity),
                ZERO_MONEY,
            ),
        )
        .filter(
            POSSale.site_id == site_id,
            POSSale.category == category,
            POSSale.status == "paid",
            POSSale.timestamp >= start_utc,
            POSSale.timestamp < end_utc,
        )
        .one()
    )

    pos_units = int(pos_result[0] or 0)
    pos_revenue = Decimal(pos_result[1] or ZERO_MONEY)

    detection_result = (
        db.query(
            func.coalesce(func.sum(Detection.count), 0),
            func.coalesce(
                func.sum(
                    case(
                        (Detection.status == "matched", Detection.count),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(
            Detection.site_id == site_id,
            Detection.category == category,
            Detection.timestamp >= start_utc,
            Detection.timestamp < end_utc,
        )
        .one()
    )

    detected_units = int(detection_result[0] or 0)
    matched_units = int(detection_result[1] or 0)

    # Only open anomalies and manager-confirmed anomalies count in the
    # official anomaly total. False alarms and auto-resolved alerts do not.
    alert_result = (
        db.query(
            func.count(Alert.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Alert.status.in_(("anomaly", "confirmed")),
                            Alert.quantity,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Alert.status.in_(("anomaly", "confirmed")),
                            Alert.estimated_loss,
                        ),
                        else_=ZERO_MONEY,
                    )
                ),
                ZERO_MONEY,
            ),
        )
        .filter(
            Alert.site_id == site_id,
            Alert.category == category,
            Alert.detected_at >= start_utc,
            Alert.detected_at < end_utc,
        )
        .one()
    )

    alerts_count = int(alert_result[0] or 0)
    anomaly_units = int(alert_result[1] or 0)
    estimated_loss = Decimal(alert_result[2] or ZERO_MONEY)

    return {
        "pos_units": pos_units,
        "pos_revenue": pos_revenue,
        "detected_units": detected_units,
        "matched_units": matched_units,
        "anomaly_units": anomaly_units,
        "alerts_count": alerts_count,
        "estimated_loss": estimated_loss,
    }


def recalculate_daily_summary(
    db: Session,
    site_id: str,
    summary_date: date,
) -> list[DailySummary]:
    """Recalculate and persist summaries for one local business date.

    One DailySummary row is maintained per site/date/category.

    This function flushes changes but does not commit the transaction.
    """

    site, settings = get_site_reporting_configuration(db, site_id)

    start_hour = settings.business_day_start if settings else 0

    start_utc, end_utc = business_day_bounds(
        summary_date,
        site.timezone_name,
        start_hour,
    )

    categories = _get_categories_for_day(
        db,
        site_id,
        start_utc,
        end_utc,
    )

    now = datetime.now(timezone.utc)
    summaries: list[DailySummary] = []

    for category in sorted(categories):
        metrics = _aggregate_category(
            db,
            site_id,
            category,
            start_utc,
            end_utc,
        )

        summary = (
            db.query(DailySummary)
            .filter(
                DailySummary.site_id == site_id,
                DailySummary.summary_date == summary_date,
                DailySummary.category == category,
            )
            .one_or_none()
        )

        if summary is None:
            summary = DailySummary(
                site_id=site_id,
                summary_date=summary_date,
                category=category,
                currency=site.currency,
            )
            db.add(summary)

        summary.pos_units = metrics["pos_units"]
        summary.pos_revenue = metrics["pos_revenue"]
        summary.detected_units = metrics["detected_units"]
        summary.matched_units = metrics["matched_units"]
        summary.anomaly_units = metrics["anomaly_units"]
        summary.alerts_count = metrics["alerts_count"]
        summary.estimated_loss = metrics["estimated_loss"]
        summary.currency = site.currency
        summary.calculated_at = now

        summaries.append(summary)

    db.flush()
    return summaries


def get_daily_summaries(
    db: Session,
    site_id: str,
    start_date: date,
    end_date: date,
    *,
    category: str | None = None,
) -> list[DailySummary]:
    """Retrieve saved daily summaries for a date range."""

    if start_date > end_date:
        raise ValueError("Invalid date range")

    query = db.query(DailySummary).filter(
        DailySummary.site_id == site_id,
        DailySummary.summary_date >= start_date,
        DailySummary.summary_date <= end_date,
    )

    if category is not None:
        query = query.filter(DailySummary.category == category)

    return (
        query.order_by(
            DailySummary.summary_date.asc(),
            DailySummary.category.asc(),
        )
        .all()
    )


def get_confirmed_estimated_loss(
    db: Session,
    site_id: str,
    start_date: date,
    end_date: date,
    *,
    category: str | None = None,
) -> Decimal:
    """Calculate the separate total confirmed by managers.

    The DailySummary database model has only one estimated_loss column.
    This helper provides the separate confirmed figure required by R11.
    """

    if start_date > end_date:
        raise ValueError("Invalid date range")

    site, settings = get_site_reporting_configuration(db, site_id)
    start_hour = settings.business_day_start if settings else 0

    start_utc, _ = business_day_bounds(
        start_date,
        site.timezone_name,
        start_hour,
    )
    _, end_utc = business_day_bounds(
        end_date,
        site.timezone_name,
        start_hour,
    )

    query = db.query(
        func.coalesce(
            func.sum(Alert.estimated_loss),
            ZERO_MONEY,
        )
    ).filter(
        Alert.site_id == site_id,
        Alert.status == "confirmed",
        Alert.detected_at >= start_utc,
        Alert.detected_at < end_utc,
    )

    if category is not None:
        query = query.filter(Alert.category == category)

    result = query.scalar()
    return Decimal(result or ZERO_MONEY)
