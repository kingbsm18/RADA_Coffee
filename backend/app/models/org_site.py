"""Organization > site > camera hierarchy, plus dashboard users."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLES = (ROLE_ADMIN, ROLE_MANAGER)


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Site(Base):
    __tablename__ = "site"

    # Natural key such as "cafe-01": it is what the edge sends in every event.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Casablanca")
    currency: Mapped[str] = mapped_column(String(3), default="MAD")
    # SHA-256 of the per-site edge key; the key itself is shown once at creation.
    edge_key_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Camera(Base):
    __tablename__ = "camera"
    __table_args__ = (UniqueConstraint("site_id", "camera_id", name="uq_camera_site_camera"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(String(64))  # e.g. "cam-1"
    name: Mapped[str | None] = mapped_column(String(200), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class User(Base):
    __tablename__ = "app_user"  # "user" is reserved in PostgreSQL

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=ROLE_MANAGER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
