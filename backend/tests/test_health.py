"""Tests for api/health.py: liveness (/health) and readiness (/health/ready)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app import database


@pytest.fixture
def broken_engine():
    """An engine that cannot connect, to simulate a database outage."""
    return create_engine("sqlite:////nonexistent-dir/secret-path.db")


def test_health(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_needs_no_authentication(client) -> None:
    assert "Authorization" not in client.headers
    assert client.get("/api/v1/health").status_code == 200


def test_liveness_does_not_depend_on_the_database(client, broken_engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", broken_engine)
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_liveness_is_get_only(client) -> None:
    assert client.post("/api/v1/health").status_code == 405
    assert client.delete("/api/v1/health").status_code == 405


def test_readiness_ok_with_a_working_database(client, engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", engine)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_is_503_when_the_database_is_down(client, broken_engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", broken_engine)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "database unavailable" in response.text


def test_readiness_does_not_leak_internal_details(client, broken_engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", broken_engine)
    body = client.get("/api/v1/health/ready").text
    assert "nonexistent-dir" not in body and "secret-path" not in body
    assert "sqlite" not in body.lower()


def test_readiness_needs_no_authentication(client, engine, monkeypatch) -> None:
    monkeypatch.setattr(database, "engine", engine)
    assert client.get("/api/v1/health/ready").status_code == 200


def test_readiness_recovers_when_the_database_returns(
    client, engine, broken_engine, monkeypatch
) -> None:
    monkeypatch.setattr(database, "engine", broken_engine)
    assert client.get("/api/v1/health/ready").status_code == 503
    monkeypatch.setattr(database, "engine", engine)
    assert client.get("/api/v1/health/ready").status_code == 200


def test_health_responses_carry_security_headers(client) -> None:
    assert client.get("/api/v1/health").headers["x-content-type-options"] == "nosniff"
