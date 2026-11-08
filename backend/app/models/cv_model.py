"""Registry of CV models and which one each site runs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow


class CvModel(Base):
    __tablename__ = "cv_model"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_cv_model_name_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(64))  # same value as Detection.model_version
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SiteModel(Base):
    __tablename__ = "site_model"

    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), primary_key=True)
    cv_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_model.id", ondelete="RESTRICT"))
    activated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
