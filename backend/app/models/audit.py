"""app/models/audit.py — TODO: implement (see docs/architecture.md)."""

"""Database model for immutable audit log entries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """Stores an immutable record of an important system action."""

    __tablename__ = "audit_logs"

    __table_args__ = (
        Index(
            "ix_audit_logs_site_created_at",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_entity",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_audit_logs_actor_created_at",
            "actor_id",
            "created_at",
        ),
    )

    # Unique audit entry identifier
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Site associated with the action.
    # Nullable for global system-level actions.
    site_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # User or system component that performed the action.
    # Examples: manager ID, "system", "edge".
    actor_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Actor classification
    # Examples: user, system, edge, integration.
    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    # Affected object
    # Examples: alert, detection, pos_sale, camera, site.
    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    entity_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Action performed
    # Examples: created, confirmed, false_alarm, auto_resolved.
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Optional context about the action.
    # Do not store passwords, tokens, or sensitive personal data here.
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Database-generated timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog("
            f"id={self.id}, "
            f"actor_id={self.actor_id!r}, "
            f"entity_type={self.entity_type!r}, "
            f"entity_id={self.entity_id!r}, "
            f"action={self.action!r}"
            f")>"
        )
