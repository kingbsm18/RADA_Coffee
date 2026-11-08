import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from conftest import PASSWORD

from app.config import settings
from app.models.org_site import User
from app.security import (
    create_access_token,
    decode_access_token,
    generate_edge_key,
    hash_edge_key,
    hash_password,
    verify_password,
)


def _user(role: str = "admin") -> User:
    return User(id=uuid.uuid4(), org_id=uuid.uuid4(), username="x", password_hash="x", role=role)


def test_password_hash_roundtrip_and_salting() -> None:
    first, second = hash_password("s3cret-pass"), hash_password("s3cret-pass")
    assert first != second  # random salt
    assert verify_password("s3cret-pass", first)
    assert not verify_password("wrong", first)


@pytest.mark.parametrize("stored", ["", "garbage", "md5$1$aa$bb", "pbkdf2_sha256$x$zz$zz"])
def test_malformed_stored_hash_never_verifies(stored: str) -> None:
    assert verify_password("anything", stored) is False


def test_token_roundtrip_carries_claims() -> None:
    user = _user("manager")
    token, expires_in = create_access_token(user)
    claims = decode_access_token(token)
    assert claims["sub"] == str(user.id) and claims["role"] == "manager"
    assert expires_in == settings.access_token_minutes * 60


def test_expired_and_tampered_tokens_are_rejected() -> None:
    expired, _ = create_access_token(_user(), now=datetime.now(timezone.utc) - timedelta(hours=3))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)

    token, _ = create_access_token(_user())
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token[:-2] + ("AA" if not token.endswith("AA") else "BB"))


def test_unsigned_token_with_alg_none_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "org": str(uuid.uuid4()), "role": "admin",
         "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())},
        key=None,
        algorithm="none",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "org": "o", "role": "admin",
         "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())},
        "another-secret-another-secret-another-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)


def test_edge_keys_are_random_and_only_hashes_are_comparable() -> None:
    assert generate_edge_key() != generate_edge_key()
    assert hash_edge_key("abc") == hash_edge_key("abc") != "abc"


# ----------------------------------------------------------------- HTTP behavior
def test_login_success_and_me(client, world) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "admin-a", "password": PASSWORD})
    assert response.status_code == 200 and response.json()["role"] == "admin"
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "admin-a"
    assert "password_hash" not in me.json()


def test_login_failures_do_not_reveal_whether_the_user_exists(client, world) -> None:
    wrong_password = client.post("/api/v1/auth/login", json={"username": "admin-a", "password": "nope"})
    unknown_user = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_inactive_user_cannot_log_in_or_use_an_old_token(client, world, db) -> None:
    user = db.query(User).filter_by(username="manager-a").one()
    user.active = False
    db.commit()
    assert client.post("/api/v1/auth/login", json={"username": "manager-a", "password": PASSWORD}).status_code == 401
    assert client.get("/api/v1/auth/me", headers=world.manager).status_code == 401  # token issued earlier


def test_login_is_throttled_after_repeated_failures(client, world) -> None:
    for _ in range(settings.login_max_failures):
        assert client.post("/api/v1/auth/login", json={"username": "admin-a", "password": "bad"}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"username": "admin-a", "password": PASSWORD})
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic abc"}],
)
def test_protected_routes_require_a_valid_bearer_token(client, world, headers) -> None:
    assert client.get("/api/v1/sites", headers=headers).status_code == 401


def test_manager_cannot_use_admin_endpoints(client, world) -> None:
    response = client.post("/api/v1/sites", json={"id": "cafe-02", "name": "x"}, headers=world.manager)
    assert response.status_code == 403


def test_other_organizations_site_looks_nonexistent(client, world) -> None:
    assert client.get(f"/api/v1/sites/{world.other_site}", headers=world.admin).status_code == 404
    assert client.get(f"/api/v1/sites/{world.site}", headers=world.other_admin).status_code == 404
