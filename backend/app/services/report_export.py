"""app/services/report_export.py — TODO: implement (see docs/architecture.md)."""

"""CSV report export for RADA Coffee.

Exports official daily summaries and manager-confirmed estimated losses.
The report uses each site's local business day, not UTC calendar dates.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.org_site import Site
from app.models.site_settings import SiteSettings
from app.models.summary import DailySummary
from app.services.summary_service import business_day_bounds


class ReportExportError(Exception):
    """Raised when a report cannot be generated."""


def _safe_csv_value(value):
    """Prevent spreadsheet formula execution in text cells."""

    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r")
    ):
        return "'" + value

    return value


def export_daily_report_csv(
    db: Session,
    site_id: str,
    start_date: date,
    end_date: date,
    *,
    category: str | None = None,
) -> str:
    """Export daily summaries as UTF-8 CSV text.

    Includes:
    - POS units and revenue.
    - Detected, matched and anomalous units.
    - Estimated loss from the official daily summary.
    - Confirmed estimated loss from manager-reviewed alerts.

    The function does not commit or modify database records.
    """

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    site = db.query(Site).filter(Site.id == site_id).one_or_none()

    if site is None:
        raise ReportExportError(f"Site {site_id!r} does not exist")

    settings = (
        db.query(SiteSettings)
        .filter(SiteSettings.site_id == site_id)
        .one_or_none()
    )

    business_day_start = (
        settings.business_day_start if settings is not None else 0
    )

    summaries_query = db.query(DailySummary).filter(
        DailySummary.site_id == site_id,
        DailySummary.summary_date >= start_date,
        DailySummary.summary_date <= end_date,
    )

    if category is not None:
        summaries_query = summaries_query.filter(
            DailySummary.category == category
        )

    summaries = (
        summaries_query.order_by(
            DailySummary.summary_date.asc(),
            DailySummary.category.asc(),
        )
        .all()
    )

    first_start, _ = business_day_bounds(
        start_date,
        site.timezone_name,
        business_day_start,
    )
    _, last_end = business_day_bounds(
        end_date,
        site.timezone_name,
        business_day_start,
    )

    confirmed_alerts_query = db.query(Alert).filter(
        Alert.site_id == site_id,
        Alert.status == "confirmed",
        Alert.detected_at >= first_start,
        Alert.detected_at < last_end,
    )

    if category is not None:
        confirmed_alerts_query = confirmed_alerts_query.filter(
            Alert.category == category
        )

    confirmed_alerts = confirmed_alerts_query.all()

    zone = ZoneInfo(site.timezone_name)
    confirmed_loss_by_day: dict[tuple[date, str], Decimal] = {}

    for alert in confirmed_alerts:
        local_time = alert.detected_at.astimezone(zone)
        alert_business_date = local_time.date()

        if local_time.hour < business_day_start:
            alert_business_date -= timedelta(days=1)

        key = (alert_business_date, alert.category)
        confirmed_loss_by_day[key] = (
            confirmed_loss_by_day.get(key, Decimal("0.00"))
            + Decimal(alert.estimated_loss)
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow(
        [
            "site_id",
            "date",
            "category",
            "currency",
            "pos_units",
            "pos_revenue",
            "detected_units",
            "matched_units",
            "anomaly_units",
            "alerts_count",
            "estimated_loss",
            "confirmed_estimated_loss",
            "calculated_at",
        ]
    )

    for summary in summaries:
        confirmed_loss = confirmed_loss_by_day.get(
            (summary.summary_date, summary.category),
            Decimal("0.00"),
        )

        writer.writerow(
            [
                _safe_csv_value(summary.site_id),
                summary.summary_date.isoformat(),
                _safe_csv_value(summary.category),
                summary.currency,
                summary.pos_units,
                str(Decimal(summary.pos_revenue)),
                summary.detected_units,
                summary.matched_units,
                summary.anomaly_units,
                summary.alerts_count,
                str(Decimal(summary.estimated_loss)),
                str(confirmed_loss),
                summary.calculated_at.isoformat(),
            ]
        )

    return output.getvalue()


def export_alerts_csv(
    db: Session,
    site_id: str,
    start_date: date,
    end_date: date,
    *,
    status: str | None = None,
    category: str | None = None,
) -> str:
    """Export individual alerts for a site's local business date range."""

    if start_date > end_date:
        raise ValueError("Invalid date range")

    site = db.query(Site).filter(Site.id == site_id).one_or_none()

    if site is None:
        raise ReportExportError(f"Site {site_id!r} does not exist")

    settings = (
        db.query(SiteSettings)
        .filter(SiteSettings.site_id == site_id)
        .one_or_none()
    )

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

    query = db.query(Alert).filter(
        Alert.site_id == site_id,
        Alert.detected_at >= start_utc,
        Alert.detected_at < end_utc,
    )

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

    alerts = query.order_by(Alert.detected_at.asc()).all()

    output = io.StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow(
        [
            "alert_id",
            "detection_event_id",
            "site_id",
            "detected_at",
            "category",
            "quantity",
            "status",
            "subtype",
            "estimated_loss",
            "minimum_estimated_loss",
            "maximum_estimated_loss",
            "currency",
            "reviewed_at",
            "reviewed_by",
            "review_note",
        ]
    )

    for alert in alerts:
        writer.writerow(
            [
                str(alert.id),
                _safe_csv_value(alert.detection_event_id),
                _safe_csv_value(alert.site_id),
                alert.detected_at.isoformat(),
                _safe_csv_value(alert.category),
                alert.quantity,
                alert.status,
                alert.subtype or "",
                str(Decimal(alert.estimated_loss)),
                str(Decimal(alert.min_estimated_loss)),
                str(Decimal(alert.max_estimated_loss)),
                alert.currency,
                alert.reviewed_at.isoformat() if alert.reviewed_at else "",
                _safe_csv_value(alert.reviewed_by or ""),
                _safe_csv_value(alert.review_note or ""),
            ]
        )

    return output.getvalue()
