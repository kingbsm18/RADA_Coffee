"""app/models/org_site.py — TODO: implement (see docs/architecture.md)."""

"""Database models for RADA AI organizations and sites."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Organization(Base):
    """A customer organization that owns one or more RADA AI sites."""

    __tablename__ = "organizations"

    __table_args__ = (
        UniqueConstraint(
            "slug",
            name="uq_organizations_slug",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_organizations_valid_status",
        ),
        Index(
            "ix_organizations_status",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Customer organization name.
    # Example: La Pause Group.
    name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    # Stable URL/API-friendly identifier.
    # Example: la-pause-group.
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Optional business contact information.
    contact_name: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )

    contact_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    contact_phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Organization("
            f"id={self.id}, "
            f"name={self.name!r}, "
            f"slug={self.slug!r}, "
            f"status={self.status!r}"
            f")>"
        )


class Site(Base):
    """A physical café or establishment belonging to an organization.

    The site ID is a string to remain compatible with visual_event.v1
    and the existing engine types, which use string site identifiers.
    """

    __tablename__ = "sites"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_sites_organization_code",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_sites_valid_status",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_sites_name_not_empty",
        ),
        Index(
            "ix_sites_organization",
            "organization_id",
        ),
        Index(
            "ix_sites_status",
            "status",
        ),
    )

    # Stable identifier used by camera events, POS records and detections.
    # Example: cafe-01.
    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Human-readable site identifier within the organization.
    # Example: rabat-hay-riad.
    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    country: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="MA",
        server_default="MA",
    )

    # IANA timezone name used for local reports and business hours.
    # Store timestamps in UTC in the database.
    timezone_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Africa/Casablanca",
        server_default="Africa/Casablanca",
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="MAD",
        server_default="MAD",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Site("
            f"id={self.id!r}, "
            f"organization_id={self.organization_id}, "
            f"code={self.code!r}, "
            f"name={self.name!r}, "
            f"status={self.status!r}"
            f")>"
        )
