from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.org_site import User
from app.schemas.analytics import DailySummaryOut, HourlyPointOut
from app.security import get_current_user, get_site_for_user
from app.services import report_export, summary_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _range(site_tz: str, from_day: date | None, to_day: date | None) -> tuple[date, date]:
    today = datetime.now(ZoneInfo(site_tz)).date()
    end = to_day or today
    start = from_day or end - timedelta(days=6)
    if start > end:
        raise HTTPException(422, "from_day is after to_day")
    if (end - start).days + 1 > summary_service.MAX_RANGE_DAYS:
        raise HTTPException(
            422,
            f"range too large (max {summary_service.MAX_RANGE_DAYS} days)",
        )
    return start, end


def _daily_rows(db: Session, site, start: date, end: date):
    rows = []
    day = start
    while day <= end:
        rows.extend(summary_service.get_daily(db, site, day))
        day += timedelta(days=1)
    return rows


@router.get("/daily", response_model=list[DailySummaryOut])
def daily(
    site_id: str,
    from_day: date | None = None,
    to_day: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    site = get_site_for_user(db, user, site_id)
    start, end = _range(site.timezone, from_day, to_day)
    return _daily_rows(db, site, start, end)


@router.get("/daily/export.csv")
def daily_export(
    site_id: str,
    from_day: date | None = None,
    to_day: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    site = get_site_for_user(db, user, site_id)
    start, end = _range(site.timezone, from_day, to_day)
    body = report_export.daily_summary_csv(_daily_rows(db, site, start, end))
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="rada-daily-{site.id}-{start}-{end}.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/hourly", response_model=list[HourlyPointOut])
def hourly(
    site_id: str,
    day: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    site = get_site_for_user(db, user, site_id)
    target = day or datetime.now(ZoneInfo(site.timezone)).date()
    return summary_service.compute_hourly(db, site, target)
