"""RADA Café Intelligence backend (modular monolith)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app import database
from app.api import alerts, analytics, auth, events, health, images, sites, websocket
from app.api import settings as settings_api
from app.config import assert_tz_database_current, settings
from app.models.org_site import ROLE_ADMIN, Organization, User
from app.security import hash_password

logger = logging.getLogger("rada")


def ensure_bootstrap_admin() -> bool:
    """Create the first organization + admin from env vars, only when no user exists."""
    if not (settings.admin_username and settings.admin_password):
        return False
    with database.SessionLocal() as db:
        if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
            return False
        org = Organization(name=settings.admin_org_name)
        db.add(org)
        db.flush()
        db.add(
            User(
                org_id=org.id,
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role=ROLE_ADMIN,
            )
        )
        db.commit()
    logger.info("bootstrap admin %r created", settings.admin_username)
    return True


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.assert_runtime_safe()
    if settings.environment != "dev":
        assert_tz_database_current()
    ensure_bootstrap_admin()
    yield


def create_app() -> FastAPI:
    is_dev = settings.environment == "dev"
    app = FastAPI(
        title="RADA Café Intelligence",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_dev else None,
    )

    if settings.cors_origin_list():
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list(),
            allow_methods=["GET", "POST", "PUT", "PATCH"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    prefix = "/api/v1"
    for module in (health, auth, sites, settings_api, events, alerts, analytics, images, websocket):
        app.include_router(module.router, prefix=prefix)
    return app


app = create_app()
