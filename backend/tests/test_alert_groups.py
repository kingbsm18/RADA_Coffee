"""R11: management by exception. Grouping by site/day/category/priority, optional bulk decisions."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.detection import Detection
from app.models.org_site import Site
from app.services import alert_service

UTC = timezone.utc


@pytest.fixture
def make_alert(db):
    def build(site, when, *, category="coffee", strong=False, est="25.00", qty=1, status="open"):
        detection = Detection(
            site_id=site, event_id=str(uuid.uuid4()), camera_id="cam-1", timestamp=when,
            category=category, count=qty, confidence=0.9, model_version="v",
        )
        db.add(detection)
        db.commit()
        alert, _ = alert_service.create_alert(
            db, detection=detection, missing_qty=qty, loss_est=Decimal(est),
            loss_min=Decimal(est) - 5, loss_max=Decimal(est) + 5, strong=strong,
        )
        if status != "open":
            alert.status = status
            db.commit()
        return alert

    return build


def T(day=5, hour=10):
    return datetime(2026, 11, day, hour, 0, tzinfo=UTC)


def summary(client, headers, **params):
    return client.get("/api/v1/alerts/summary", params=params, headers=headers)


# ------------------------------------------------------------------ priority
def test_priority_follows_the_strong_flag_everywhere(client, world, make_alert) -> None:
    make_alert(world.site, T(), strong=True)
    make_alert(world.site, T(hour=11), strong=False)
    items = client.get("/api/v1/alerts", params={"site_id": world.site}, headers=world.manager).json()["items"]
    assert sorted((a["strong"], a["priority"]) for a in items) == [(False, "normal"), (True, "high")]
    high = client.get("/api/v1/alerts", params={"site_id": world.site, "priority": "high"}, headers=world.manager)
    assert [a["priority"] for a in high.json()["items"]] == ["high"]
    assert client.get("/api/v1/alerts", params={"site_id": world.site, "priority": "urgent"}, headers=world.manager).status_code == 422


# ------------------------------------------------------------------ grouping
def test_groups_by_day_category_and_priority_with_the_two_loss_indicators(client, world, make_alert) -> None:
    make_alert(world.site, T(), strong=True, est="50.00", qty=2)  # open, high
    make_alert(world.site, T(hour=11), strong=True, est="25.00", status="confirmed")
    make_alert(world.site, T(hour=12), strong=True, est="25.00", status="false_alarm")
    make_alert(world.site, T(hour=13), strong=True, est="25.00", status="auto_resolved")
    make_alert(world.site, T(hour=14), strong=False, est="25.00")  # same day/category, normal
    make_alert(world.site, T(hour=15), category="soft_drink", est="18.00")
    make_alert(world.site, T(day=6), strong=True, est="25.00")  # another day
    body = summary(client, world.manager, site_id=world.site, from_day="2026-11-05", to_day="2026-11-06").json()

    keys = [(g["day"], g["category"], g["priority"]) for g in body["groups"]]
    assert keys == [
        ("2026-11-06", "coffee", "high"),
        ("2026-11-05", "coffee", "high"),
        ("2026-11-05", "coffee", "normal"),
        ("2026-11-05", "soft_drink", "normal"),
    ]
    high = body["groups"][1]
    assert high["count"] == 4 and high["missing_qty"] == 5
    assert high["by_status"] == {"open": 1, "confirmed": 1, "false_alarm": 1, "auto_resolved": 1}
    # perte détectée = open + confirmed; false_alarm and auto_resolved are excluded
    assert Decimal(high["loss_detected_est"]) == Decimal("75.00") and Decimal(high["loss_confirmed"]) == Decimal("25.00")
    assert high["open_count"] == 1 and len(high["open_alert_ids"]) == 1
    assert body["totals"]["count"] == 7
    assert Decimal(body["totals"]["loss_detected"]) == Decimal("75.00") + 25 + 18 + 25
    assert Decimal(body["totals"]["loss_confirmed"]) == Decimal("25.00")


def test_unreviewed_alerts_stay_open_and_nothing_asks_for_a_decision(client, world, make_alert, db) -> None:
    alert = make_alert(world.site, T())
    for _ in range(3):
        assert summary(client, world.manager, site_id=world.site, from_day="2026-11-05", to_day="2026-11-05").status_code == 200
    db.expire_all()
    assert db.get(Alert, alert.id).status == "open" and db.get(Alert, alert.id).reviewed_by is None


def test_day_is_the_sites_local_day(client, world, make_alert, db) -> None:
    db.get(Site, world.site).timezone = "Europe/Paris"  # UTC+1 in November
    db.commit()
    make_alert(world.site, datetime(2026, 11, 4, 23, 30, tzinfo=UTC))  # 00:30 local on the 5th
    groups = summary(client, world.manager, site_id=world.site, from_day="2026-11-04", to_day="2026-11-05").json()["groups"]
    assert [g["day"] for g in groups] == ["2026-11-05"]


def test_filters_and_validation(client, world, make_alert) -> None:
    make_alert(world.site, T(), strong=True)
    make_alert(world.site, T(hour=11), category="soft_drink")
    h, base = world.manager, {"site_id": world.site, "from_day": "2026-11-05", "to_day": "2026-11-05"}
    assert [g["category"] for g in summary(client, h, **base, category="soft_drink").json()["groups"]] == ["soft_drink"]
    assert [g["priority"] for g in summary(client, h, **base, priority="high").json()["groups"]] == ["high"]
    assert summary(client, h, site_id=world.site, from_day="2026-11-06", to_day="2026-11-05").status_code == 422
    assert summary(client, h, site_id=world.site, from_day="2026-01-01", to_day="2026-11-05").status_code == 422
    assert summary(client, h, **base, priority="urgent").status_code == 422
    assert summary(client, h, site_id=world.site).status_code == 200  # default: last 7 days


def test_all_sites_of_the_organization_and_no_leak_across_organizations(client, world, make_alert) -> None:
    make_alert(world.site, T())
    make_alert(world.other_site, T())  # belongs to the other organization
    body = summary(client, world.manager, from_day="2026-11-05", to_day="2026-11-05").json()
    assert [g["site_id"] for g in body["groups"]] == [world.site]
    assert summary(client, world.manager, site_id=world.other_site).status_code == 404
    assert summary(client, {}, site_id=world.site).status_code == 401


# ------------------------------------------------------------------ group review (optional)
def review_many(client, headers, ids, status="false_alarm", note=None):
    return client.post("/api/v1/alerts/review", json={"alert_ids": [str(i) for i in ids], "status": status, "note": note}, headers=headers)


def test_a_whole_group_can_be_qualified_in_one_request(client, world, make_alert, db) -> None:
    alerts = [make_alert(world.site, T(hour=10 + i)) for i in range(3)]
    group = summary(client, world.manager, site_id=world.site, from_day="2026-11-05", to_day="2026-11-05").json()["groups"][0]
    assert sorted(group["open_alert_ids"]) == sorted(str(a.id) for a in alerts)

    response = review_many(client, world.manager, group["open_alert_ids"], "false_alarm", "livraison, pas une vente")
    assert response.status_code == 200 and response.json()["updated"] == 3
    db.expire_all()
    for alert in alerts:
        row = db.get(Alert, alert.id)
        assert row.status == "false_alarm" and row.review_note == "livraison, pas une vente"
        assert row.reviewed_by is not None and row.resolved_at is not None  # timestamped and attributed
        assert db.get(Detection, row.detection_id).state == "false_alarm"
    audits = db.query(AuditLog).filter_by(action="alert.review").all()
    assert len(audits) == 3 and all(a.detail["bulk"] and a.actor_label == "manager-a" for a in audits)
    after = summary(client, world.manager, site_id=world.site, from_day="2026-11-05", to_day="2026-11-05").json()
    assert after["groups"][0]["open_count"] == 0 and Decimal(after["totals"]["loss_detected"]) == 0


def test_group_review_is_all_or_nothing(client, world, make_alert, db) -> None:
    good = make_alert(world.site, T())
    final = make_alert(world.site, T(hour=11), status="auto_resolved")  # R13 outcome cannot be reviewed
    response = review_many(client, world.manager, [good.id, final.id])
    assert response.status_code == 409 and str(final.id) in response.json()["detail"]
    db.expire_all()
    assert db.get(Alert, good.id).status == "open"  # untouched
    assert db.query(AuditLog).filter_by(action="alert.review").count() == 0


def test_group_review_access_control_and_validation(client, world, make_alert, db) -> None:
    mine, foreign = make_alert(world.site, T()), make_alert(world.other_site, T())
    assert review_many(client, world.manager, [mine.id, foreign.id]).status_code == 404  # nothing changes
    assert review_many(client, world.manager, [mine.id, uuid.uuid4()]).status_code == 404
    db.expire_all()
    assert db.get(Alert, mine.id).status == "open"
    assert review_many(client, world.manager, []).status_code == 422
    assert review_many(client, world.manager, [mine.id, mine.id]).status_code == 422
    assert review_many(client, world.manager, [uuid.uuid4() for _ in range(201)]).status_code == 422
    assert review_many(client, world.manager, [mine.id], "open").status_code == 422
    assert review_many(client, {}, [mine.id]).status_code == 401
    assert review_many(client, world.manager, [mine.id], "confirmed").status_code == 200
