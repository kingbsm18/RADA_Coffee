import pytest
from sqlalchemy import select

from app import database, main
from app.config import Settings
from app.models.org_site import ROLE_ADMIN, Organization, User


def strong(**overrides) -> Settings:
    values = dict(environment="hybrid", secret_key="s" * 40, database_url="postgresql+psycopg://rada:Zk3x9@db/rada")
    values.update(overrides)
    return Settings(**values)


def test_dev_accepts_defaults_but_other_environments_do_not() -> None:
    Settings(environment="dev").assert_runtime_safe()
    for bad in (
        dict(secret_key="change_me"),
        dict(secret_key="short"),
        dict(admin_password="tooshort"),
        dict(database_url="postgresql+psycopg://rada:change_me@db/rada"),
    ):
        with pytest.raises(RuntimeError):
            strong(**bad).assert_runtime_safe()
    strong(admin_password="a-long-enough-password").assert_runtime_safe()


def test_bootstrap_creates_the_first_admin_once(client, session_factory, db, monkeypatch) -> None:
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.config.settings.admin_username", "founder")
    monkeypatch.setattr("app.config.settings.admin_password", "a-long-enough-password")
    assert main.ensure_bootstrap_admin() is True
    assert main.ensure_bootstrap_admin() is False  # users exist: nothing happens
    user = db.execute(select(User)).scalar_one()
    assert user.username == "founder" and user.role == ROLE_ADMIN
    assert user.password_hash.startswith("pbkdf2_sha256$") and "a-long-enough-password" not in user.password_hash
    assert db.query(Organization).count() == 1
    login = client.post("/api/v1/auth/login", json={"username": "founder", "password": "a-long-enough-password"})
    assert login.status_code == 200


def test_bootstrap_is_disabled_without_credentials(session_factory, monkeypatch) -> None:
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.config.settings.admin_username", None)
    assert main.ensure_bootstrap_admin() is False


def test_docs_are_hidden_outside_dev(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.environment", "hybrid")
    production = main.create_app()
    assert production.docs_url is None and production.openapi_url is None
    monkeypatch.setattr("app.config.settings.environment", "dev")
    assert main.create_app().docs_url == "/docs"


def test_security_headers_and_health(client) -> None:
    response = client.get("/api/v1/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"


def test_readiness_reflects_the_database(client, engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", engine)
    assert client.get("/api/v1/health/ready").json() == {"status": "ready"}
    from sqlalchemy import create_engine

    monkeypatch.setattr(database, "engine", create_engine("sqlite:////nonexistent-dir/x.db"))
    assert client.get("/api/v1/health/ready").status_code == 503


def test_feature_flags(monkeypatch) -> None:
    from app.features.flags import enabled_flags, is_enabled

    monkeypatch.setattr("app.config.settings.feature_flags", " a, b ,,c")
    assert enabled_flags() == {"a", "b", "c"} and is_enabled("b") and not is_enabled("z")
