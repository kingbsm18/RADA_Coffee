import os

import pytest
from conftest import JPEG

from app.infra.storage import (
    InvalidSnapshotRef,
    SnapshotTooLarge,
    StorageError,
    get_storage,
    validate_ref,
)
from app.infra.storage_local import LocalStorage
from app.infra.storage_s3 import S3Storage
from app.models.audit import AuditLog
from app.models.detection import Detection

REF = "snap/2026-11-05/104213_cam1.jpg"


@pytest.mark.parametrize(
    "ref",
    ["../x", "/abs/path", "a/../b", "a//b", "a/./b", "a/", "", ".hidden/../x", "a\\b", "a b", "x\x00y", "é.jpg", "a" * 300, "~/x"],
)
def test_dangerous_snapshot_refs_are_rejected(ref: str) -> None:
    with pytest.raises(InvalidSnapshotRef):
        validate_ref(ref)


def test_normal_refs_are_accepted() -> None:
    for ref in (REF, "a.jpg", "2026-11-05/x_1.png", "cam-1/a.b.c"):
        assert validate_ref(ref) == ref


def test_local_storage_roundtrip_and_no_overwrite(tmp_path) -> None:
    store = LocalStorage(tmp_path, max_bytes=1000)
    assert store.save("cafe-01", REF, b"one") is True
    assert store.save("cafe-01", REF, b"two") is False  # retry keeps the original
    assert store.read("cafe-01", REF) == b"one" and store.exists("cafe-01", REF)
    assert store.read("cafe-01", "snap/missing.jpg") is None
    store.delete("cafe-01", REF)
    assert not store.exists("cafe-01", REF)
    store.delete("cafe-01", REF)  # idempotent
    assert not list(tmp_path.rglob("*.tmp"))  # no temp files left behind


def test_local_storage_limits_and_isolation(tmp_path) -> None:
    store = LocalStorage(tmp_path, max_bytes=10)
    with pytest.raises(SnapshotTooLarge):
        store.save("cafe-01", REF, b"x" * 11)
    store.save("cafe-01", REF, b"a")
    assert store.read("cafe-02", REF) is None  # sites are isolated
    for bad_site in ("../cafe", "/etc", "a/../../b"):
        with pytest.raises(InvalidSnapshotRef):
            store.read(bad_site, REF)


def test_symlink_cannot_escape_the_storage_root(tmp_path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"secret")
    (root / "cafe-01").mkdir()
    os.symlink(outside, root / "cafe-01" / "link")
    with pytest.raises(InvalidSnapshotRef):
        LocalStorage(root, max_bytes=100).read("cafe-01", "link/secret.jpg")


class _NotFound(Exception):
    response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[dict] = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts.append({"Key": Key, **kwargs})
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        import io

        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


def test_s3_storage_with_a_fake_client() -> None:
    client = FakeS3()
    store = S3Storage("bucket", prefix="/snapshots/", max_bytes=10, client=client)
    assert store.save("cafe-01", REF, b"abc") is True
    assert store.save("cafe-01", REF, b"zzz") is False
    assert list(client.objects) == [f"snapshots/cafe-01/{REF}"]
    assert client.puts[0]["ServerSideEncryption"] == "AES256"
    assert store.read("cafe-01", REF) == b"abc" and store.read("cafe-01", "snap/none.jpg") is None
    with pytest.raises(SnapshotTooLarge):
        store.save("cafe-01", "snap/big.jpg", b"x" * 11)
    with pytest.raises(InvalidSnapshotRef):
        store.save("cafe-01", "../x", b"a")
    store.delete("cafe-01", REF)
    assert not store.exists("cafe-01", REF)


def test_storage_factory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.config.settings.storage_backend", "local")
    monkeypatch.setattr("app.config.settings.snapshot_dir", str(tmp_path))
    get_storage.cache_clear()
    assert isinstance(get_storage(), LocalStorage)
    monkeypatch.setattr("app.config.settings.storage_backend", "s3")
    monkeypatch.setattr("app.config.settings.s3_bucket", None)
    get_storage.cache_clear()
    with pytest.raises(StorageError, match="S3_BUCKET"):
        get_storage()
    monkeypatch.setattr("app.config.settings.storage_backend", "tape")
    get_storage.cache_clear()
    with pytest.raises(StorageError, match="unknown"):
        get_storage()
    get_storage.cache_clear()


# ---------------------------------------------------------------- HTTP
def upload(client, world, *, ref=REF, data=JPEG, headers=None, site=None, name="a.jpg"):
    return client.post(
        "/api/v1/images",
        data={"site_id": site or world.site, "snapshot_ref": ref},
        files={"file": (name, data, "image/jpeg")},
        headers=world.edge if headers is None else headers,
    )


def test_edge_uploads_a_snapshot_and_retries_are_harmless(client, world) -> None:
    first = upload(client, world)
    assert first.status_code == 201 and first.json() == {"status": "created"}
    again = upload(client, world)
    assert again.status_code == 200 and again.json() == {"status": "duplicate"}


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"data": b"not an image at all"}, 415),
        ({"data": b"<html><script>alert(1)</script></html>"}, 415),
        ({"data": JPEG + b"x" * 100_000}, 413),
        ({"ref": "../../etc/passwd"}, 422),
        ({"ref": "/etc/passwd"}, 422),
        ({"headers": {}}, 401),
        ({"headers": {"X-Edge-Key": "nope"}}, 401),
    ],
)
def test_bad_uploads_are_rejected(client, world, kwargs, expected) -> None:
    assert upload(client, world, **kwargs).status_code == expected


def test_a_site_key_cannot_upload_for_another_site(client, world) -> None:
    assert upload(client, world, site=world.other_site).status_code == 401


def test_manager_views_a_snapshot_and_the_access_is_audited(client, world, db) -> None:
    upload(client, world)
    response = client.get(f"/api/v1/images/{world.site}/{REF}", headers=world.manager)
    assert response.status_code == 200 and response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert "no-store" in response.headers["cache-control"]
    audit = db.query(AuditLog).filter_by(action="image.view").one()
    assert audit.actor_label == "manager-a" and audit.target_id == REF


def test_snapshot_access_control(client, world) -> None:
    upload(client, world)
    url = f"/api/v1/images/{world.site}/{REF}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=world.other_admin).status_code == 404
    assert client.get(url, headers=world.edge).status_code == 401  # edge key is write-only
    assert client.get(f"/api/v1/images/{world.site}/snap/none.jpg", headers=world.manager).status_code == 404


@pytest.mark.parametrize("ref", ["a/../b.jpg", "%2e%2e/%2e%2e/etc/passwd", "..%2Fsecret.jpg", "a%00b.jpg"])
def test_traversal_attempts_never_return_data(client, world, ref) -> None:
    upload(client, world)
    response = client.get(f"/api/v1/images/{world.site}/{ref}", headers=world.manager)
    assert response.status_code in (400, 404) and response.content[:3] != b"\xff\xd8\xff"


def test_listing_returns_all_photos_of_a_category_in_the_period(client, world, db) -> None:
    from datetime import datetime, timezone

    for index, category in enumerate(("coffee", "coffee", "soft_drink")):
        db.add(Detection(
            site_id=world.site, event_id=f"e{index}", camera_id="cam-1",
            timestamp=datetime(2026, 11, 5, 10, index, tzinfo=timezone.utc),
            category=category, count=1, confidence=0.9, model_version="v0.1",
            snapshot_ref=f"snap/{index}.jpg",
        ))
    db.add(Detection(site_id=world.site, event_id="nophoto", camera_id="cam-1",
                     timestamp=datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc),
                     category="coffee", count=1, confidence=0.9, model_version="v0.1"))
    db.commit()
    params = {"category": "coffee", "since": "2026-11-05T00:00:00Z", "until": "2026-11-06T00:00:00Z"}
    items = client.get(f"/api/v1/sites/{world.site}/images", params=params, headers=world.manager).json()
    assert [i["url"] for i in items] == [f"/api/v1/images/{world.site}/snap/0.jpg", f"/api/v1/images/{world.site}/snap/1.jpg"]
    assert db.query(AuditLog).filter_by(action="image.list").count() == 1
    naive = {**params, "since": "2026-11-05T00:00:00"}
    assert client.get(f"/api/v1/sites/{world.site}/images", params=naive, headers=world.manager).status_code == 422
    assert client.get(f"/api/v1/sites/{world.site}/images", params=params, headers=world.other_admin).status_code == 404
