from datetime import datetime, timedelta, timezone

import pytest

from app.models.org_site import Camera


def post(client, world, payload, headers=None):
    return client.post("/api/v1/events", json=payload, headers=world.edge if headers is None else headers)


def test_event_is_created_then_replays_are_harmless_duplicates(client, world, make_event) -> None:
    payload = make_event()
    first = post(client, world, payload)
    assert first.status_code == 201 and first.json()["status"] == "created"
    for _ in range(3):
        again = post(client, world, payload)
        assert again.status_code == 200 and again.json() == {
            "status": "duplicate", "id": first.json()["id"],
        }
    listing = client.get("/api/v1/events", params={"site_id": world.site}, headers=world.manager)
    assert listing.json()["total"] == 1


def test_same_event_id_with_different_content_is_a_conflict(client, world, make_event) -> None:
    payload = make_event()
    assert post(client, world, payload).status_code == 201
    assert post(client, world, {**payload, "count": 2}).status_code == 409


def test_offset_timestamp_is_stored_as_the_same_instant(client, world, make_event) -> None:
    local = (datetime.now(timezone.utc) - timedelta(minutes=5)).astimezone(timezone(timedelta(hours=1)))
    assert post(client, world, make_event(timestamp=local.isoformat())).status_code == 201
    item = client.get("/api/v1/events", params={"site_id": world.site}, headers=world.manager).json()["items"][0]
    assert datetime.fromisoformat(item["timestamp"]) == local


@pytest.mark.parametrize("headers", [{}, {"X-Edge-Key": "wrong"}])
def test_missing_or_wrong_edge_key_is_rejected(client, world, make_event, headers) -> None:
    assert post(client, world, make_event(), headers=headers).status_code == 401


def test_a_sites_key_cannot_write_to_another_site(client, world, make_event) -> None:
    response = post(client, world, make_event(site_id=world.other_site), headers=world.edge)
    assert response.status_code == 401


def test_dashboard_token_is_not_an_edge_credential(client, world, make_event) -> None:
    assert post(client, world, make_event(), headers=world.admin).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"count": 0},
        {"count": 101},
        {"confidence": 1.2},
        {"confidence": -0.1},
        {"timestamp": "2026-11-05T10:42:13"},  # no UTC offset
        {"event_id": "not-a-uuid"},
        {"schema": "visual_event.v2"},
        {"site_id": "bad site!"},
        {"unexpected": "field"},
    ],
)
def test_invalid_payloads_are_rejected(client, world, make_event, overrides) -> None:
    assert post(client, world, make_event(**overrides)).status_code == 422


def test_unknown_category_is_rejected(client, world, make_event) -> None:
    response = post(client, world, make_event(category="pizza"))
    assert response.status_code == 422 and "category" in response.json()["detail"]


def test_events_from_the_future_are_rejected(client, world, make_event) -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    response = post(client, world, make_event(timestamp=future))
    assert response.status_code == 422 and "future" in response.json()["detail"]


def test_old_events_are_accepted_for_outbox_replays(client, world, make_event) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    assert post(client, world, make_event(timestamp=old)).status_code == 201


def test_camera_is_registered_and_last_seen_updated(client, world, make_event, db) -> None:
    post(client, world, make_event(camera_id="cam-7"))
    camera = db.query(Camera).filter_by(site_id=world.site, camera_id="cam-7").one()
    assert camera.last_seen_at is not None


def test_listing_filters_and_pagination(client, world, make_event) -> None:
    for category in ("coffee", "coffee", "soft_drink"):
        assert post(client, world, make_event(category=category)).status_code == 201
    params = {"site_id": world.site}
    h = world.manager
    assert client.get("/api/v1/events", params={**params, "category": "coffee"}, headers=h).json()["total"] == 2
    page = client.get("/api/v1/events", params={**params, "limit": 2}, headers=h).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert client.get("/api/v1/events", params={**params, "state": "pending"}, headers=h).json()["total"] == 3
    assert client.get("/api/v1/events", params={**params, "state": "bogus"}, headers=h).status_code == 422
    assert client.get("/api/v1/events", params={**params, "since": "2026-11-05T10:00:00"}, headers=h).status_code == 422
    assert client.get("/api/v1/events", params={**params, "limit": 1000}, headers=h).status_code == 422


def test_listing_requires_auth_and_org_membership(client, world, make_event) -> None:
    post(client, world, make_event())
    assert client.get("/api/v1/events", params={"site_id": world.site}).status_code == 401
    assert client.get("/api/v1/events", params={"site_id": world.site}, headers=world.other_admin).status_code == 404
