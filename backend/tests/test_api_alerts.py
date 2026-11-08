import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.detection import Detection
from app.services import alert_service


@pytest.fixture
def make_detection(db, world):
    def build(*, count: int = 2, category: str = "coffee", **extra) -> Detection:
        detection = Detection(
            site_id=world.site, event_id=str(uuid.uuid4()), camera_id="cam-1",
            timestamp=extra.pop("timestamp", datetime.now(timezone.utc) - timedelta(hours=1)),
            category=category, count=count, confidence=0.9, model_version="v0.1", **extra,
        )
        db.add(detection)
        db.commit()
        return detection

    return build


@pytest.fixture
def alert(db, make_detection) -> Alert:
    created, _ = alert_service.create_alert(
        db, detection=make_detection(), missing_qty=2,
        loss_est=Decimal("50.00"), loss_min=Decimal("40.00"), loss_max=Decimal("60.00"),
    )
    return created


def test_creating_an_alert_marks_the_detection_and_is_idempotent(db, make_detection) -> None:
    detection = make_detection()
    first, created = alert_service.create_alert(
        db, detection=detection, missing_qty=1,
        loss_est=Decimal("25.00"), loss_min=Decimal("20.00"), loss_max=Decimal("30.00"),
    )
    again, created_again = alert_service.create_alert(  # engine re-run with other prices
        db, detection=detection, missing_qty=2,
        loss_est=Decimal("99.00"), loss_min=Decimal("90.00"), loss_max=Decimal("99.00"),
    )
    assert created and not created_again and again.id == first.id
    assert again.loss_est == Decimal("25.00") and again.missing_qty == 1  # frozen at creation (R10)
    assert db.get(Detection, detection.id).state == "anomaly"
    assert db.query(Alert).count() == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"missing_qty": 0},
        {"missing_qty": 3},  # more than the detection count
        {"loss_min": Decimal("60.00")},  # min above estimate
        {"loss_max": Decimal("10.00")},
        {"loss_est": Decimal("-1.00"), "loss_min": Decimal("-2.00")},
    ],
)
def test_alert_inputs_are_validated(db, make_detection, kwargs) -> None:
    base = dict(missing_qty=1, loss_est=Decimal("25.00"), loss_min=Decimal("20.00"), loss_max=Decimal("30.00"))
    with pytest.raises(alert_service.AlertError):
        alert_service.create_alert(db, detection=make_detection(count=2), **{**base, **kwargs})


def test_the_database_itself_rejects_inconsistent_loss_ranges(db, make_detection) -> None:
    detection = make_detection()
    db.add(Alert(site_id=detection.site_id, detection_id=detection.id, category="coffee",
                 missing_qty=1, loss_est=Decimal("10"), loss_min=Decimal("20"), loss_max=Decimal("30")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_a_detection_can_only_have_one_alert_at_the_database_level(db, alert) -> None:
    db.add(Alert(site_id=alert.site_id, detection_id=alert.detection_id, category="coffee",
                 missing_qty=1, loss_est=Decimal("1"), loss_min=Decimal("1"), loss_max=Decimal("1")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_manager_confirms_an_alert(client, world, alert, db) -> None:
    response = client.patch(
        f"/api/v1/alerts/{alert.id}", json={"status": "confirmed", "note": "vérifié sur place"},
        headers=world.manager,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed" and body["resolved_at"] and body["review_note"] == "vérifié sur place"
    db.expire_all()
    assert db.get(Detection, alert.detection_id).state == "confirmed"
    audit = db.query(AuditLog).filter_by(action="alert.review").one()
    assert audit.actor_label == "manager-a" and audit.detail == {"from": "open", "to": "confirmed"}


def test_manager_can_change_their_mind_but_not_review_auto_resolved(client, world, alert, db) -> None:
    url = f"/api/v1/alerts/{alert.id}"
    assert client.patch(url, json={"status": "confirmed"}, headers=world.manager).status_code == 200
    assert client.patch(url, json={"status": "false_alarm"}, headers=world.manager).json()["status"] == "false_alarm"
    db.expire_all()
    assert db.get(Detection, alert.detection_id).state == "false_alarm"

    row = db.get(Alert, alert.id)
    row.status = "auto_resolved"  # R13 outcome is final
    db.commit()
    assert client.patch(url, json={"status": "confirmed"}, headers=world.manager).status_code == 409


@pytest.mark.parametrize("body", [{"status": "open"}, {"status": "auto_resolved"}, {}, {"status": "confirmed", "note": "x" * 2001}])
def test_invalid_reviews_are_rejected(client, world, alert, body) -> None:
    assert client.patch(f"/api/v1/alerts/{alert.id}", json=body, headers=world.manager).status_code == 422


def test_alerts_of_other_organizations_are_invisible(client, world, alert) -> None:
    assert client.get(f"/api/v1/alerts/{alert.id}", headers=world.other_admin).status_code == 404
    assert client.patch(f"/api/v1/alerts/{alert.id}", json={"status": "confirmed"}, headers=world.other_admin).status_code == 404
    assert client.get("/api/v1/alerts", params={"site_id": world.site}, headers=world.other_admin).status_code == 404
    assert client.get(f"/api/v1/alerts/{uuid.uuid4()}", headers=world.admin).status_code == 404
    assert client.get(f"/api/v1/alerts/{alert.id}").status_code == 401


def test_listing_filters_and_amounts_are_exact_strings(client, world, alert, make_detection, db) -> None:
    second, _ = alert_service.create_alert(
        db, detection=make_detection(count=1, category="soft_drink"), missing_qty=1,
        loss_est=Decimal("18.00"), loss_min=Decimal("15.00"), loss_max=Decimal("20.00"),
    )
    client.patch(f"/api/v1/alerts/{second.id}", json={"status": "false_alarm"}, headers=world.manager)
    h, params = world.manager, {"site_id": world.site}

    everything = client.get("/api/v1/alerts", params=params, headers=h).json()
    assert everything["total"] == 2
    assert {a["loss_est"] for a in everything["items"]} == {"50.00", "18.00"}  # strings, never floats
    assert client.get("/api/v1/alerts", params={**params, "status_filter": "open"}, headers=h).json()["total"] == 1
    assert client.get("/api/v1/alerts", params={**params, "category": "soft_drink"}, headers=h).json()["total"] == 1
    assert client.get("/api/v1/alerts", params={**params, "status_filter": "bogus"}, headers=h).status_code == 422
    assert client.get("/api/v1/alerts", params={**params, "limit": 1}, headers=h).json()["items"].__len__() == 1
