"""Replays must never create duplicates: edge retries, re-imports, engine re-runs."""

import os
from decimal import Decimal

import pytest

from app.models.alert import Alert
from app.models.detection import Detection
from app.models.pos_sale import PosImportBatch, PosSale

HEADER = "external_id,timestamp,product_name,pos_category,quantity,unit_price,status\n"
CSV = HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,2,25.00,paid\n2,2026-11-05T10:05:00Z,Coca,Soft,1,18.00,paid\n"


def test_replaying_an_event_ten_times_keeps_one_row(client, world, make_event, db) -> None:
    payload = make_event()
    statuses = [client.post("/api/v1/events", json=payload, headers=world.edge).status_code for _ in range(10)]
    assert statuses == [201] + [200] * 9
    assert db.query(Detection).count() == 1


def test_event_ids_are_scoped_per_site(client, world, make_event, db) -> None:
    payload = make_event()
    other = {**payload, "site_id": world.other_site}
    assert client.post("/api/v1/events", json=payload, headers=world.edge).status_code == 201
    assert client.post("/api/v1/events", json=other, headers=world.other_edge).status_code == 201
    assert db.query(Detection).count() == 2


def test_lost_insert_race_is_recovered_as_a_duplicate(client, world, make_event, db, monkeypatch) -> None:
    """Two requests pass the 'already exists?' check at once; the unique constraint decides."""
    from app.api import events

    payload = make_event()
    assert client.post("/api/v1/events", json=payload, headers=world.edge).status_code == 201

    real_find, calls = events._find, []

    def blind_first_lookup(*args, **kwargs):
        calls.append(1)
        return None if len(calls) == 1 else real_find(*args, **kwargs)

    monkeypatch.setattr(events, "_find", blind_first_lookup)
    again = client.post("/api/v1/events", json=payload, headers=world.edge)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert db.query(Detection).count() == 1

    # ...and a racing request with different content is still a conflict
    calls.clear()
    assert client.post("/api/v1/events", json={**payload, "count": 3}, headers=world.edge).status_code == 409


def upload(client, world, text):
    return client.post(
        f"/api/v1/sites/{world.site}/pos/import", files={"file": ("a.csv", text.encode(), "text/csv")}, headers=world.manager
    ).json()


def test_reimporting_the_same_file_changes_nothing(client, world, db) -> None:
    upload(client, world, CSV)
    before = {(s.external_id, s.status, s.unit_price, s.timestamp) for s in db.query(PosSale)}
    for _ in range(3):
        report = upload(client, world, CSV)
        assert (report["rows_inserted"], report["rows_updated"], report["rows_unchanged"]) == (0, 0, 2)
    db.expire_all()
    assert {(s.external_id, s.status, s.unit_price, s.timestamp) for s in db.query(PosSale)} == before
    assert db.query(PosImportBatch).count() == 4  # every attempt is audited, none duplicates data


def test_overlapping_exports_only_add_the_new_rows(client, world, db) -> None:
    upload(client, world, CSV)
    report = upload(client, world, CSV + "3,2026-11-05T10:10:00Z,Café,Chaud,1,25.00,paid\n")
    assert (report["rows_inserted"], report["rows_unchanged"]) == (1, 2)
    assert db.query(PosSale).count() == 3


def test_money_survives_the_roundtrip_exactly(client, world, db) -> None:
    upload(client, world, HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,1,0.10,paid\n2,2026-11-05T10:00:00Z,Café,Chaud,1,19.99,paid\n")
    db.expire_all()
    prices = {s.external_id: s.unit_price for s in db.query(PosSale)}
    assert prices == {"1": Decimal("0.10"), "2": Decimal("19.99")}
    assert all(isinstance(p, Decimal) for p in prices.values())


def test_the_database_enforces_one_sale_per_site_and_external_id(db, world) -> None:
    from datetime import datetime, timezone

    from sqlalchemy.exc import IntegrityError

    def row():
        return PosSale(site_id=world.site, external_id="dup", timestamp=datetime(2026, 11, 5, tzinfo=timezone.utc),
                       product_name="p", quantity=1, unit_price=Decimal("1"), status="paid")

    db.add(row())
    db.commit()
    db.add(row())
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL")
def test_concurrent_identical_events_create_exactly_one_row(client, world, make_event, db) -> None:
    from concurrent.futures import ThreadPoolExecutor

    payload = make_event()
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: client.post("/api/v1/events", json=payload, headers=world.edge).status_code, range(16)))
    assert sorted(set(codes)) in ([200, 201], [201]) and codes.count(201) == 1
    assert db.query(Detection).count() == 1 and db.query(Alert).count() == 0
