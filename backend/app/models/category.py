"""Categories and the single POS -> category mapping table."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MATCH_FIELDS = ("product_name", "pos_category")


class Category(Base):
    """A category the detector can output and the POS can be mapped to."""

    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_category_site_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))  # e.g. "coffee", "soft_drink"
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CategoryMapping(Base):
    """Maps a POS product name or POS category to one of the site's categories."""

    __tablename__ = "category_mapping"
    __table_args__ = (
        UniqueConstraint("site_id", "match_field", "match_value", name="uq_category_mapping_key"),
        CheckConstraint("match_field IN ('product_name', 'pos_category')", name="match_field_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    match_field: Mapped[str] = mapped_column(String(20))
    match_value: Mapped[str] = mapped_column(String(200))  # stored casefolded + stripped
    category: Mapped[str] = mapped_column(String(64))
