"""Links between a detection unit and the POS credit it consumed (R6)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CreditLink(Base):
    """One row per matched detection unit. A credit is consumed at most once."""

    __tablename__ = "credit_link"
    __table_args__ = (
        UniqueConstraint("site_id", "credit_id", name="uq_credit_link_site_credit"),
        UniqueConstraint("detection_id", "unit_index", name="uq_credit_link_detection_unit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detection.id", ondelete="CASCADE"), index=True
    )
    unit_index: Mapped[int] = mapped_column(Integer)
    credit_id: Mapped[str] = mapped_column(String(64))  # id produced by engine.credits
