"""app/models/cv_model.py — TODO: implement (see docs/architecture.md)."""

"""Database model for computer vision model versions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CVModel(Base):
    """Represents a versioned computer vision model used by RADA AI."""

    __tablename__ = "cv_models"

    __table_args__ = (
        UniqueConstraint(
            "name",
            "version",
            name="uq_cv_models_name_version",
        ),
        CheckConstraint(
            "status IN ('development', 'staging', 'production', 'retired')",
            name="ck_cv_models_valid_status",
        ),
        Index(
            "ix_cv_models_status",
            "status",
        ),
        Index(
            "ix_cv_models_active",
            "is_active",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Model identification
    # Examples: handover_detector, beverage_detector.
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Model artifact information.
    # Store a path or object-storage reference, never the model binary itself.
    artifact_uri: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )

    artifact_checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    framework: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="ultralytics",
        server_default="ultralytics",
    )

    # Model lifecycle
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="development",
        server_default="development",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # Optional model metadata.
    # Examples: input size, supported categories, runtime configuration.
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        nullable=True,
    )

    # Deployment and lifecycle timestamps
    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
            f"<CVModel("
            f"id={self.id}, "
            f"name={self.name!r}, "
            f"version={self.version!r}, "
            f"status={self.status!r}, "
            f"is_active={self.is_active}"
            f")>"
        )
