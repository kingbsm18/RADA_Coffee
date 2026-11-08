"""Authentication and authorization.

- Dashboard users: username/password -> short-lived HS256 JWT (Bearer).
- Edge devices: one random key per site, sent as ``X-Edge-Key``; only its SHA-256
  is stored. The edge can write events/snapshots for its own site and nothing else.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.org_site import ROLE_ADMIN, Site, User

JWT_ALGORITHM = "HS256"
_PBKDF2_PREFIX = "pbkdf2_sha256"
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- passwords
def hash_password(password: str, *, iterations: int | None = None) -> str:
    iterations = iterations or settings.password_hash_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_PBKDF2_PREFIX}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations, salt_hex, digest_hex = stored.split("$")
        if prefix != _PBKDF2_PREFIX:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------------------------------------------------------------- tokens
def create_access_token(user: User, *, now: datetime | None = None) -> tuple[str, int]:
    now = now or datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": str(user.id),
        "org": str(user.org_id),
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict:
    """Return the claims or raise ``jwt.PyJWTError``."""
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub", "org", "role"]},
    )


# ---------------------------------------------------------------- login throttle
class LoginThrottle:
    """In-memory, per-process brute-force guard (per username and per client IP)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        window = settings.login_window_seconds
        events = self._failures[key]
        while events and now - events[0] > window:
            events.popleft()
        return events

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(
                len(self._prune(key, now)) >= settings.login_max_failures for key in keys
            )

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()


# ---------------------------------------------------------------- edge keys
def generate_edge_key() -> str:
    return secrets.token_urlsafe(32)


def hash_edge_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def verify_edge_key(db: Session, site_id: str, provided: str | None) -> Site:
    """Authenticate an edge device for ``site_id`` or raise 401 (never reveals why)."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid edge credentials")
    site = db.get(Site, site_id)
    expected = site.edge_key_hash if site and site.active else None
    candidate = hash_edge_key(provided or "")
    # Always compare something so the response time does not reveal valid site ids.
    if not hmac.compare_digest(candidate, expected or hash_edge_key(secrets.token_hex(8))):
        raise unauthorized
    if not (site and site.active and expected):
        raise unauthorized
    return site


def edge_key_header(x_edge_key: str | None = Header(default=None)) -> str | None:
    return x_edge_key


# ---------------------------------------------------------------- dashboard users
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise unauthorized
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return dependency


require_admin = require_roles(ROLE_ADMIN)


def get_site_for_user(db: Session, user: User, site_id: str) -> Site:
    """Return the site if it belongs to the user's organization, else 404.

    404 (not 403) so users cannot probe which site ids exist in other organizations.
    """
    site = db.execute(
        select(Site).where(Site.id == site_id, Site.org_id == user.org_id)
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site
