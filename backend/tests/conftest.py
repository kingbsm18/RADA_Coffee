"""Test fixtures. SQLite in memory by default; set TEST_DATABASE_URL to run the same
suite against PostgreSQL (CI should do this: money columns are NUMERIC there)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all tables)
from app.config import settings
from app.database import Base, get_db
from app.infra.storage import get_storage
from app.infra.storage_local import LocalStorage
from app.main import app
from app.models.org_site import ROLE_ADMIN, ROLE_MANAGER, Organization, User
from app.security import hash_password, login_throttle
from app.services.notification import hub

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "password_hash_iterations", 1_000)
    monkeypatch.setattr(settings, "secret_key", "t" * 48)
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "snapshot_max_bytes", 100_000)
    login_throttle.clear()
    hub._subscribers.clear()
    hub._loop = None
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def engine():
    if TEST_DATABASE_URL:
        eng = create_engine(TEST_DATABASE_URL)
    else:
        eng = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(eng, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "snapshots", max_bytes=settings.snapshot_max_bytes)


@pytest.fixture
def client(session_factory, storage) -> TestClient:
    def override_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def world(client: TestClient, db: Session) -> SimpleNamespace:
    """Two organizations. Org A: admin + manager + site cafe-01. Org B: admin + other-01."""
    org_a, org_b = Organization(name="Org A"), Organization(name="Org B")
    db.add_all([org_a, org_b])
    db.flush()
    for username, org, role in (
        ("admin-a", org_a, ROLE_ADMIN),
        ("manager-a", org_a, ROLE_MANAGER),
        ("admin-b", org_b, ROLE_ADMIN),
    ):
        db.add(
            User(
                org_id=org.id,
                username=username,
                password_hash=hash_password(PASSWORD),
                role=role,
            )
        )
    db.commit()

    admin, manager, other_admin = (
        _login(client, "admin-a"),
        _login(client, "manager-a"),
        _login(client, "admin-b"),
    )
    site = client.post("/api/v1/sites", json={"id": "cafe-01", "name": "Café 01"}, headers=admin)
    other = client.post("/api/v1/sites", json={"id": "other-01", "name": "Other"}, headers=other_admin)
    assert site.status_code == 201 and other.status_code == 201
    return SimpleNamespace(
        admin=admin,
        manager=manager,
        other_admin=other_admin,
        site="cafe-01",
        edge_key=site.json()["edge_key"],
        edge={"X-Edge-Key": site.json()["edge_key"]},
        other_site="other-01",
        other_edge={"X-Edge-Key": other.json()["edge_key"]},
        org_a=org_a.id,
        org_b=org_b.id,
    )


@pytest.fixture
def make_event(world: SimpleNamespace) -> Callable[..., dict]:
    def build(**overrides) -> dict:
        payload = {
            "schema": "visual_event.v1",
            "event_id": str(uuid.uuid4()),
            "site_id": world.site,
            "camera_id": "cam-1",
            "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "category": "coffee",
            "count": 1,
            "confidence": 0.91,
            "snapshot_ref": None,
            "model_version": "v0.1",
        }
        payload.update(overrides)
        return payload

    return build


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
