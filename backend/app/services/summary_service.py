"""Daily and hourly aggregates for the dashboard (computed on the site's local day).

``cv_qty`` is what the camera saw; ``pos_qty`` is paid POS units. The loss figures and
``gap_qty`` come from alerts only (the engine decides what is an anomaly): a raw
``cv_qty - pos_qty`` is NOT used as a loss, because matching is per unit and windowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.category import Category
from app.models.detection import Detection
from app.models.org_site import Site
from app.models.pos_sale import PosSale
from app.models.summary import DailySummary

MAX_RANGE_DAYS = 62
_CENT = Decimal("0.01")


@dataclass(slots=True)
class DailyRow:
    day: date
    category: str
    pos_qty: int = 0
    cv_qty: int = 0
    gap_qty: int = 0
    loss_est: Decimal = Decimal("0.00")
    loss_min: Decimal = Decimal("0.00")
    loss_max: Decimal = Decimal("0.00")
    loss_confirmed: Decimal = Decimal("0.00")
    pending_count: int = 0
    false_alarm_count: int = 0
    is_final: bool = False


@dataclass(slots=True)
class HourlyRow:
    hour: int
    category: str
    pos_qty: int = 0
    cv_qty: int = 0


def day_bounds_utc(tz: ZoneInfo, day: date) -> tuple[datetime, datetime]:
    """[start, end) of the local day in UTC (handles 23h/25h days)."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENT)


def _site_categories(db: Session, site_id: str) -> list[str]:
    return list(
        db.execute(
            select(Category.name).where(Category.site_id == site_id, Category.active.is_(True))
        ).scalars()
    )


def compute_daily(db: Session, site: Site, day: date) -> list[DailyRow]:
    tz = ZoneInfo(site.timezone)
    start, end = day_bounds_utc(tz, day)
    rows: dict[str, DailyRow] = {name: DailyRow(day, name) for name in _site_categories(db, site.id)}

    def row(category: str) -> DailyRow:
        return rows.setdefault(category, DailyRow(day, category))

    for category, qty in db.execute(
        select(PosSale.category, func.sum(PosSale.quantity)).where(
            PosSale.site_id == site.id,
            PosSale.status == "paid",
            PosSale.category.is_not(None),
            PosSale.timestamp >= start,
            PosSale.timestamp < end,
        ).group_by(PosSale.category)
    ):
        row(category).pos_qty = int(qty or 0)

    detection_filter = (
        Detection.site_id == site.id,
        Detection.timestamp >= start,
        Detection.timestamp < end,
    )
    for category, qty in db.execute(
        select(Detection.category, func.sum(Detection.count))
        .where(*detection_filter)
        .group_by(Detection.category)
    ):
        row(category).cv_qty = int(qty or 0)

    for category, count in db.execute(
        select(Detection.category, func.count())
        .where(*detection_filter, Detection.state == "pending")
        .group_by(Detection.category)
    ):
        row(category).pending_count = int(count)

    alert_rows = db.execute(
        select(
            Alert.category,
            Alert.status,
            func.count(),
            func.sum(Alert.missing_qty),
            func.sum(Alert.loss_est),
            func.sum(Alert.loss_min),
            func.sum(Alert.loss_max),
        )
        .join(Detection, Detection.id == Alert.detection_id)
        .where(*detection_filter)
        .group_by(Alert.category, Alert.status)
    )
    for category, status, count, missing, est, low, high in alert_rows:
        target = row(category)
        if status == "false_alarm":
            target.false_alarm_count += int(count)
        if status in ("open", "confirmed"):
            target.gap_qty += int(missing or 0)
            target.loss_est += _money(est)
            target.loss_min += _money(low)
            target.loss_max += _money(high)
        if status == "confirmed":
            target.loss_confirmed += _money(est)

    return [rows[name] for name in sorted(rows)]


def compute_hourly(db: Session, site: Site, day: date) -> list[HourlyRow]:
    tz = ZoneInfo(site.timezone)
    start, end = day_bounds_utc(tz, day)
    buckets: dict[tuple[int, str], HourlyRow] = {}

    def bucket(timestamp: datetime, category: str) -> HourlyRow:
        hour = timestamp.astimezone(tz).hour
        return buckets.setdefault((hour, category), HourlyRow(hour, category))

    for timestamp, category, quantity in db.execute(
        select(PosSale.timestamp, PosSale.category, PosSale.quantity).where(
            PosSale.site_id == site.id,
            PosSale.status == "paid",
            PosSale.category.is_not(None),
            PosSale.timestamp >= start,
            PosSale.timestamp < end,
        )
    ):
        bucket(timestamp, category).pos_qty += int(quantity)
    for timestamp, category, count in db.execute(
        select(Detection.timestamp, Detection.category, Detection.count).where(
            Detection.site_id == site.id, Detection.timestamp >= start, Detection.timestamp < end
        )
    ):
        bucket(timestamp, category).cv_qty += int(count)
    return [buckets[key] for key in sorted(buckets)]


def get_daily(db: Session, site: Site, day: date) -> list[DailyRow]:
    """Final (post-R13) stored rows when they exist, otherwise live figures."""
    stored = list(
        db.execute(
            select(DailySummary).where(
                DailySummary.site_id == site.id, DailySummary.day == day, DailySummary.is_final.is_(True)
            )
        ).scalars()
    )
    if stored:
        return [
            DailyRow(
                day=s.day, category=s.category, pos_qty=s.pos_qty, cv_qty=s.cv_qty,
                gap_qty=s.gap_qty, loss_est=s.loss_est, loss_min=s.loss_min, loss_max=s.loss_max,
                loss_confirmed=s.loss_confirmed, pending_count=s.pending_count,
                false_alarm_count=s.false_alarm_count, is_final=True,
            )
            for s in sorted(stored, key=lambda item: item.category)
        ]
    return compute_daily(db, site, day)


def persist_daily(db: Session, site: Site, day: date, *, is_final: bool = False) -> int:
    """Store the day's figures. A final day is never overwritten by a non-final run."""
    existing = {
        s.category: s
        for s in db.execute(
            select(DailySummary).where(DailySummary.site_id == site.id, DailySummary.day == day)
        ).scalars()
    }
    written = 0
    for item in compute_daily(db, site, day):
        current = existing.get(item.category)
        if current is not None and current.is_final and not is_final:
            continue
        if current is None:
            current = DailySummary(site_id=site.id, day=day, category=item.category)
            db.add(current)
        for name in (
            "pos_qty", "cv_qty", "gap_qty", "loss_est", "loss_min", "loss_max",
            "loss_confirmed", "pending_count", "false_alarm_count",
        ):
            setattr(current, name, getattr(item, name))
        current.is_final = is_final
        written += 1
    db.commit()
    return written
