from __future__ import annotations

from functools import cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.org_site import User
from app.schemas.auth import LoginIn, MeOut, TokenOut
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    login_throttle,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    user_key = f"user:{payload.username.casefold()}"
    ip_key = f"ip:{request.client.host if request.client else 'unknown'}"
    if login_throttle.blocked(user_key, ip_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts, try again later",
            headers={"Retry-After": "300"},
        )

    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    # Verify against a dummy hash when the user is unknown: same response time.
    valid = verify_password(payload.password, user.password_hash if user else _dummy_hash())
    if user is None or not user.active or not valid:
        login_throttle.record_failure(user_key, ip_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    login_throttle.reset(user_key)
    token, expires_in = create_access_token(user)
    return TokenOut(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
