"""Append-only audit log (snapshot access, alert reviews, imports)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONType, UTCDateTime, utcnow


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_site_ts", "site_id", "ts"),
        Index("ix_audit_log_action_ts", "action", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)  # no FK: log outlives users
    actor_label: Mapped[str] = mapped_column(String(120))  # username or "edge:<site_id>"
    action: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[str | None] = mapped_column(String(64), default=None)
    target_type: Mapped[str | None] = mapped_column(String(32), default=None)
    target_id: Mapped[str | None] = mapped_column(String(255), default=None)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)


def record_audit(
    db,
    *,
    actor_label: str,
    action: str,
    site_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row to the session (committed with the caller's transaction)."""
    entry = AuditLog(
        actor_label=actor_label,
        actor_user_id=actor_user_id,
        action=action,
        site_id=site_id,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(entry)
    return entry
