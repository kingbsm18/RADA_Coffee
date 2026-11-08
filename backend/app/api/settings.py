"""Per-site settings (windows, threshold) and the POS -> category mapping."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.types import CategoryWindows
from app.models.audit import record_audit
from app.models.category import Category, CategoryMapping
from app.models.org_site import User
from app.models.site_settings import SiteSettingsModel
from app.pos.category_mapping import normalize_key
from app.pos.sync import remap_categories
from app.schemas.settings import (
    CategoryMappingItem,
    CategoryMappingsIn,
    CategoryMappingsOut,
    SiteSettingsIn,
    SiteSettingsOut,
    WindowsIn,
)
from app.security import get_current_user, get_site_for_user, require_admin

router = APIRouter(prefix="/sites/{site_id}", tags=["settings"])


def _to_out(row: SiteSettingsModel) -> SiteSettingsOut:
    return SiteSettingsOut(
        site_id=row.site_id,
        confidence_threshold=row.confidence_threshold,
        windows={name: WindowsIn(**values) for name, values in row.windows.items()},
        snapshot_retention_days=row.snapshot_retention_days,
        snapshot_upload_policy=row.snapshot_upload_policy,
        updated_at=row.updated_at,
    )


@router.get("/settings", response_model=SiteSettingsOut)
def get_settings(
    site_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SiteSettingsOut:
    get_site_for_user(db, user, site_id)
    row = db.get(SiteSettingsModel, site_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Settings not found")
    return _to_out(row)


@router.put("/settings", response_model=SiteSettingsOut)
def put_settings(
    site_id: str,
    payload: SiteSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SiteSettingsOut:
    get_site_for_user(db, user, site_id)
    for windows in payload.windows.values():  # same bounds as the engine (<= 30 min)
        CategoryWindows(lookback=timedelta(minutes=windows.lookback), grace=timedelta(minutes=windows.grace))

    row = db.get(SiteSettingsModel, site_id) or SiteSettingsModel(site_id=site_id)
    row.confidence_threshold = payload.confidence_threshold
    row.windows = {name: values.model_dump() for name, values in payload.windows.items()}
    row.snapshot_retention_days = payload.snapshot_retention_days
    row.snapshot_upload_policy = payload.snapshot_upload_policy
    db.add(row)

    # Categories follow the configured windows: add missing ones, deactivate removed ones.
    existing = {c.name: c for c in db.execute(select(Category).where(Category.site_id == site_id)).scalars()}
    for name in payload.windows:
        if name in existing:
            existing[name].active = True
        else:
            db.add(Category(site_id=site_id, name=name))
    for name, category in existing.items():
        if name not in payload.windows:
            category.active = False

    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="settings.update",
        site_id=site_id,
        detail={"categories": sorted(payload.windows)},
    )
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("/category-mappings", response_model=CategoryMappingsOut)
def get_mappings(
    site_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> CategoryMappingsOut:
    get_site_for_user(db, user, site_id)
    rows = db.execute(
        select(CategoryMapping)
        .where(CategoryMapping.site_id == site_id)
        .order_by(CategoryMapping.match_field, CategoryMapping.match_value)
    ).scalars()
    return CategoryMappingsOut(
        items=[CategoryMappingItem(match_field=r.match_field, match_value=r.match_value, category=r.category) for r in rows]
    )


@router.put("/category-mappings", response_model=CategoryMappingsOut)
def put_mappings(
    site_id: str,
    payload: CategoryMappingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> CategoryMappingsOut:
    """Replace the whole mapping, then re-resolve the category of existing POS sales."""
    get_site_for_user(db, user, site_id)
    active = set(
        db.execute(
            select(Category.name).where(Category.site_id == site_id, Category.active.is_(True))
        ).scalars()
    )
    resolved: dict[tuple[str, str], str] = {}
    for item in payload.items:
        if item.category not in active:
            raise HTTPException(
                422, f"unknown category: {item.category!r}"
            )
        key = (item.match_field, normalize_key(item.match_value))
        if not key[1]:
            raise HTTPException(422, "match_value is empty")
        if resolved.get(key, item.category) != item.category:
            raise HTTPException(
                422,
                f"conflicting mappings for {item.match_field}={item.match_value!r}",
            )
        resolved[key] = item.category

    db.execute(delete(CategoryMapping).where(CategoryMapping.site_id == site_id))
    for (field, value), category in resolved.items():
        db.add(CategoryMapping(site_id=site_id, match_field=field, match_value=value, category=category))
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="category_mapping.update",
        site_id=site_id,
        detail={"entries": len(resolved)},
    )
    db.commit()
    remap_categories(db, site_id)
    return CategoryMappingsOut(
        items=[CategoryMappingItem(match_field=f, match_value=v, category=c) for (f, v), c in sorted(resolved.items())]
    )
