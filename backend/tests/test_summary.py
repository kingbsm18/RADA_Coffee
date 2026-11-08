import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.alert import Alert
from app.models.detection import Detection
from app.models.org_site import Site
from app.models.pos_sale import PosSale
from app.models.summary import DailySummary
from app.services import report_export, summary_service
from app.services.summary_service import DailyRow, day_bounds_utc

UTC = timezone.utc
DAY = date(2026, 11, 5)


def utc(h: int, m: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=UTC)


def sale(site, external_id, when, category="coffee", qty=1, price="25.00", status="paid") -> PosSale:
    return PosSale(site_id=site, external_id=external_id, timestamp=when, product_name="p",
                   category=category, quantity=qty, unit_price=Decimal(price), status=status)


def detection(site, when, category="coffee", count=1, state="pending") -> Detection:
    return Detection(site_id=site, event_id=str(uuid.uuid4()), camera_id="cam-1", timestamp=when,
                     category=category, count=count, confidence=0.9, model_version="v", state=state)


def alert_for(db, det, status, qty, est, low, high) -> None:
    db.add(det)
    db.flush()
    db.add(Alert(site_id=det.site_id, detection_id=det.id, category=det.category, missing_qty=qty,
                 loss_est=Decimal(est), loss_min=Decimal(low), loss_max=Decimal(high), status=status))


def test_day_bounds_handle_the_25_hour_day_when_morocco_moved_back_to_utc0() -> None:
    tz = ZoneInfo("Africa/Casablanca")
    start, end = day_bounds_utc(tz, date(2026, 9, 20))
    assert start == datetime(2026, 9, 19, 23, 0, tzinfo=UTC)  # local midnight was still UTC+1
    assert end == datetime(2026, 9, 21, 0, 0, tzinfo=UTC)  # next midnight is UTC+0
    assert (end - start).total_seconds() == 25 * 3600
    start, end = day_bounds_utc(tz, DAY)
    assert (start, end) == (utc(0), utc(0, day=6))


def test_daily_figures(db, world) -> None:
    site = db.get(Site, world.site)
    db.add_all([
        sale(world.site, "1", utc(10), qty=2),
        sale(world.site, "2", utc(11), qty=1),
        sale(world.site, "3", utc(12), status="voided"),  # not a credit
        sale(world.site, "4", utc(13), category=None),  # unmapped: ignored
        sale(world.site, "5", utc(14), category="soft_drink", price="0.00"),  # free item counts (R3)
        sale(world.site, "6", datetime(2026, 11, 4, 23, 59, tzinfo=UTC)),  # previous day
        detection(world.site, utc(10), count=2),
        detection(world.site, utc(15), category="soft_drink"),
    ])
    alert_for(db, detection(world.site, utc(16), count=2, state="anomaly"), "open", 2, "50.00", "40.00", "60.00")
    alert_for(db, detection(world.site, utc(17), state="confirmed"), "confirmed", 1, "25.00", "20.00", "30.00")
    alert_for(db, detection(world.site, utc(18), state="false_alarm"), "false_alarm", 1, "25.00", "20.00", "30.00")
    alert_for(db, detection(world.site, utc(19), state="auto_resolved"), "auto_resolved", 1, "25.00", "20.00", "30.00")
    db.commit()

    rows = {r.category: r for r in summary_service.compute_daily(db, site, DAY)}
    coffee, soda = rows["coffee"], rows["soft_drink"]
    assert (coffee.pos_qty, soda.pos_qty) == (3, 1)
    assert coffee.cv_qty == 2 + 2 + 1 + 1 + 1 and soda.cv_qty == 1
    assert coffee.pending_count == 1 and soda.pending_count == 1
    assert coffee.gap_qty == 3  # open (2) + confirmed (1); false alarms and auto-resolved excluded
    assert (coffee.loss_est, coffee.loss_min, coffee.loss_max) == (Decimal("75.00"), Decimal("60.00"), Decimal("90.00"))
    assert coffee.loss_confirmed == Decimal("25.00") and coffee.false_alarm_count == 1


def test_days_follow_the_sites_local_timezone(db, world) -> None:
    site = db.get(Site, world.site)
    site.timezone = "Europe/Paris"  # UTC+1 in November
    db.add_all([sale(world.site, "late", datetime(2026, 11, 4, 23, 30, tzinfo=UTC)),
                detection(world.site, datetime(2026, 11, 4, 23, 30, tzinfo=UTC))])
    db.commit()
    paris_day = {r.category: r for r in summary_service.compute_daily(db, site, DAY)}["coffee"]
    assert paris_day.pos_qty == 1 and paris_day.cv_qty == 1  # 00:30 local on the 5th
    assert {r.category: r for r in summary_service.compute_daily(db, site, date(2026, 11, 4))}["coffee"].pos_qty == 0
    hourly = summary_service.compute_hourly(db, site, DAY)
    assert [(h.hour, h.category, h.pos_qty, h.cv_qty) for h in hourly] == [(0, "coffee", 1, 1)]


def test_hourly_buckets(db, world) -> None:
    site = db.get(Site, world.site)
    db.add_all([sale(world.site, "a", utc(10, 5), qty=2), sale(world.site, "b", utc(10, 50)),
                sale(world.site, "c", utc(11, 0), category="soft_drink"), detection(world.site, utc(10, 20), count=3)])
    db.commit()
    points = {(p.hour, p.category): (p.pos_qty, p.cv_qty) for p in summary_service.compute_hourly(db, site, DAY)}
    assert points == {(10, "coffee"): (3, 3), (11, "soft_drink"): (1, 0)}


def test_final_days_are_frozen_and_never_overwritten_by_live_runs(db, world) -> None:
    site = db.get(Site, world.site)
    db.add(sale(world.site, "1", utc(10)))
    db.commit()
    assert summary_service.persist_daily(db, site, DAY) == 2  # coffee + soft_drink, not final
    assert summary_service.persist_daily(db, site, DAY, is_final=True) == 2

    db.add(sale(world.site, "late", utc(12)))  # arrives after the recalculation
    db.commit()
    assert summary_service.persist_daily(db, site, DAY) == 0  # final rows are left alone
    final = {r.category: r for r in summary_service.get_daily(db, site, DAY)}
    assert final["coffee"].pos_qty == 1 and final["coffee"].is_final
    assert db.query(DailySummary).count() == 2


def test_analytics_endpoints(client, world, db) -> None:
    db.add_all([sale(world.site, "1", utc(10), qty=2), detection(world.site, utc(10))])
    db.commit()
    h = world.manager
    daily = client.get("/api/v1/analytics/daily", params={"site_id": world.site, "from_day": "2026-11-05", "to_day": "2026-11-05"}, headers=h)
    assert daily.status_code == 200
    assert {r["category"]: r["pos_qty"] for r in daily.json()} == {"coffee": 2, "soft_drink": 0}
    assert daily.json()[0]["loss_est"] == "0.00"  # money as strings

    hourly = client.get("/api/v1/analytics/hourly", params={"site_id": world.site, "day": "2026-11-05"}, headers=h).json()
    assert hourly == [{"hour": 10, "category": "coffee", "pos_qty": 2, "cv_qty": 1}]

    bad = {"site_id": world.site}
    assert client.get("/api/v1/analytics/daily", params={**bad, "from_day": "2026-11-06", "to_day": "2026-11-05"}, headers=h).status_code == 422
    assert client.get("/api/v1/analytics/daily", params={**bad, "from_day": "2026-01-01", "to_day": "2026-11-05"}, headers=h).status_code == 422
    assert client.get("/api/v1/analytics/daily", params=bad, headers=h).status_code == 200  # default: last 7 days
    assert client.get("/api/v1/analytics/daily", params=bad, headers=world.other_admin).status_code == 404
    assert client.get("/api/v1/analytics/daily", params=bad).status_code == 401


def test_csv_export(client, world, db) -> None:
    db.add(sale(world.site, "1", utc(10)))
    db.commit()
    response = client.get("/api/v1/analytics/daily/export.csv",
                          params={"site_id": world.site, "from_day": "2026-11-05", "to_day": "2026-11-05"}, headers=world.manager)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().split("\n")
    assert lines[0].startswith("day,category,pos_qty") and lines[1].startswith("2026-11-05,coffee,1,0,0,0.00")


@pytest.mark.parametrize("cell", ["=HYPERLINK(\"http://evil\")", "+1+1", "-2", "@SUM(A1)", "\tx"])
def test_csv_cells_cannot_be_spreadsheet_formulas(cell) -> None:
    out = report_export.daily_summary_csv([DailyRow(day=DAY, category=cell)])
    assert out.split("\n")[1].split(",")[1].lstrip('"').startswith("'")
