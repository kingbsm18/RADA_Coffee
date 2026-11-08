import pytest

from app.models.audit import AuditLog
from app.models.pos_sale import PosSale

CSV = (
    "external_id,timestamp,product_name,pos_category,quantity,unit_price,status\n"
    "1,2026-11-05T10:00:00Z,Café,Chaud,2,25.00,paid\n"
    "2,2026-11-05T10:05:00Z,Coca,Soft,1,18.00,paid\n"
)


def test_site_creation_returns_the_edge_key_once_and_stores_only_a_hash(client, world, db) -> None:
    from app.models.org_site import Site

    created = client.post("/api/v1/sites", json={"id": "cafe-02", "name": "Café 02"}, headers=world.admin)
    assert created.status_code == 201
    key = created.json()["edge_key"]
    assert len(key) >= 40 and key not in client.get("/api/v1/sites/cafe-02", headers=world.admin).text
    assert db.get(Site, "cafe-02").edge_key_hash != key


@pytest.mark.parametrize(
    "body",
    [
        {"id": "cafe-01", "name": "dup"},  # already exists (any organization)
        {"id": "Bad Id!", "name": "x"},
        {"id": "ok-1", "name": "x", "timezone": "Mars/Base"},
        {"id": "ok-2", "name": "x", "currency": "mad"},
        {"id": "ok-3", "name": ""},
    ],
)
def test_invalid_site_creation(client, world, body) -> None:
    assert client.post("/api/v1/sites", json=body, headers=world.admin).status_code in (409, 422)


def test_sites_are_listed_per_organization(client, world) -> None:
    assert [s["id"] for s in client.get("/api/v1/sites", headers=world.admin).json()] == ["cafe-01"]
    assert [s["id"] for s in client.get("/api/v1/sites", headers=world.other_admin).json()] == ["other-01"]


def test_rotating_the_edge_key_revokes_the_old_one(client, world, make_event) -> None:
    assert client.post("/api/v1/events", json=make_event(), headers=world.edge).status_code == 201
    rotated = client.post(f"/api/v1/sites/{world.site}/edge-key/rotate", headers=world.admin)
    assert rotated.status_code == 200
    assert client.post("/api/v1/events", json=make_event(), headers=world.edge).status_code == 401
    new = {"X-Edge-Key": rotated.json()["edge_key"]}
    assert client.post("/api/v1/events", json=make_event(), headers=new).status_code == 201
    assert client.post(f"/api/v1/sites/{world.site}/edge-key/rotate", headers=world.manager).status_code == 403


def test_default_settings_are_within_the_engine_bounds(client, world) -> None:

    settings = client.get(f"/api/v1/sites/{world.site}/settings", headers=world.manager).json()
    assert set(settings["windows"]) == {"coffee", "soft_drink"}
    assert all(0 <= w["lookback"] <= 30 and 0 <= w["grace"] <= 30 for w in settings["windows"].values())


def test_settings_convert_to_the_pure_engine_type(client, world, db) -> None:
    from datetime import timedelta

    from app.models.site_settings import SiteSettingsModel

    engine_settings = db.get(SiteSettingsModel, world.site).to_engine()
    assert engine_settings.windows_for("coffee").grace == timedelta(minutes=12)
    assert engine_settings.confidence_threshold == 0.6


def put_settings(client, world, **overrides):
    body = {
        "confidence_threshold": 0.7,
        "windows": {"coffee": {"lookback": 20, "grace": 10}, "tea": {"lookback": 15, "grace": 5}},
        "snapshot_retention_days": 14,
        "snapshot_upload_policy": "always",
    }
    body.update(overrides)
    return client.put(f"/api/v1/sites/{world.site}/settings", json=body, headers=overrides.pop("_h", world.admin))


def test_settings_update_syncs_categories_and_is_audited(client, world, make_event, db) -> None:
    assert put_settings(client, world).status_code == 200
    assert client.post("/api/v1/events", json=make_event(category="tea"), headers=world.edge).status_code == 201
    # soft_drink was removed from the windows, so it is no longer an accepted category
    assert client.post("/api/v1/events", json=make_event(category="soft_drink"), headers=world.edge).status_code == 422
    assert db.query(AuditLog).filter_by(action="settings.update").count() == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"windows": {"coffee": {"lookback": 31, "grace": 5}}},  # above the 30-minute ceiling
        {"windows": {"coffee": {"lookback": -1, "grace": 5}}},
        {"windows": {}},
        {"confidence_threshold": 1.5},
        {"snapshot_upload_policy": "sometimes"},
        {"snapshot_retention_days": 0},
    ],
)
def test_invalid_settings_are_rejected(client, world, overrides) -> None:
    assert put_settings(client, world, **overrides).status_code == 422


def test_only_admins_change_settings_and_other_orgs_cannot_read_them(client, world) -> None:
    assert client.put(
        f"/api/v1/sites/{world.site}/settings", json={}, headers=world.manager
    ).status_code == 403
    assert client.get(f"/api/v1/sites/{world.site}/settings", headers=world.other_admin).status_code == 404


def test_mapping_replaces_all_entries_and_remaps_existing_sales(client, world, db) -> None:
    client.post(
        f"/api/v1/sites/{world.site}/pos/import",
        files={"file": ("a.csv", CSV.encode(), "text/csv")},
        headers=world.manager,
    )
    assert {s.category for s in db.query(PosSale).all()} == {None}

    body = {"items": [
        {"match_field": "pos_category", "match_value": "  CHAUD ", "category": "coffee"},
        {"match_field": "product_name", "match_value": "coca", "category": "soft_drink"},
    ]}
    response = client.put(f"/api/v1/sites/{world.site}/category-mappings", json=body, headers=world.admin)
    assert response.status_code == 200
    assert response.json()["items"][0]["match_value"] == "chaud"  # normalized
    db.expire_all()
    assert {s.product_name: s.category for s in db.query(PosSale).all()} == {"Café": "coffee", "Coca": "soft_drink"}
    assert len(client.get(f"/api/v1/sites/{world.site}/category-mappings", headers=world.manager).json()["items"]) == 2


def test_invalid_mappings_are_rejected(client, world) -> None:
    url = f"/api/v1/sites/{world.site}/category-mappings"
    unknown = {"items": [{"match_field": "product_name", "match_value": "x", "category": "pizza"}]}
    assert client.put(url, json=unknown, headers=world.admin).status_code == 422
    conflict = {"items": [
        {"match_field": "product_name", "match_value": "X", "category": "coffee"},
        {"match_field": "product_name", "match_value": " x ", "category": "soft_drink"},
    ]}
    assert client.put(url, json=conflict, headers=world.admin).status_code == 422
    bad_field = {"items": [{"match_field": "sku", "match_value": "x", "category": "coffee"}]}
    assert client.put(url, json=bad_field, headers=world.admin).status_code == 422
    assert client.put(url, json={"items": []}, headers=world.manager).status_code == 403
