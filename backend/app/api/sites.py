"""Sites, edge keys and POS imports."""

from __future__ import annotations

import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.audit import record_audit
from app.models.category import Category
from app.models.org_site import Site, User
from app.models.pos_sale import PosImportBatch
from app.models.site_settings import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_WINDOWS_MINUTES,
    SiteSettingsModel,
)
from app.pos.adapters.csv_import import CsvImportAdapter
from app.pos.base import PosImportError
from app.pos.sync import import_sales
from app.schemas.events import ImportReportOut, RowErrorOut
from app.schemas.settings import EdgeKeyOut, ImportBatchOut, SiteCreatedOut, SiteCreateIn, SiteOut
from app.security import (
    generate_edge_key,
    get_current_user,
    get_site_for_user,
    hash_edge_key,
    require_admin,
)

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(select(Site).where(Site.org_id == user.org_id).order_by(Site.id)).scalars().all()


@router.post("", response_model=SiteCreatedOut, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: SiteCreateIn, db: Session = Depends(get_db), user: User = Depends(require_admin)
) -> SiteCreatedOut:
    try:
        ZoneInfo(payload.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "unknown timezone") from None
    if db.get(Site, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "site id already exists")

    edge_key = generate_edge_key()
    site = Site(
        id=payload.id,
        org_id=user.org_id,
        name=payload.name,
        timezone=payload.timezone,
        currency=payload.currency,
        edge_key_hash=hash_edge_key(edge_key),
    )
    db.add(site)
    # Models declare no relationship(), so the unit of work cannot infer the insert order:
    # flush the parent explicitly before adding rows that reference it.
    db.flush()
    db.add(
        SiteSettingsModel(
            site_id=payload.id,
            confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
            windows={name: dict(values) for name, values in DEFAULT_WINDOWS_MINUTES.items()},
        )
    )
    for name in DEFAULT_WINDOWS_MINUTES:
        db.add(Category(site_id=payload.id, name=name))
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="site.create",
        site_id=payload.id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "site id already exists") from None
    return SiteCreatedOut(site=SiteOut.model_validate(site), edge_key=edge_key)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_site_for_user(db, user, site_id)


@router.post("/{site_id}/edge-key/rotate", response_model=EdgeKeyOut)
def rotate_edge_key(
    site_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)
) -> EdgeKeyOut:
    """The old key stops working immediately; the new one is shown once."""
    site = get_site_for_user(db, user, site_id)
    edge_key = generate_edge_key()
    site.edge_key_hash = hash_edge_key(edge_key)
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="site.edge_key_rotate",
        site_id=site_id,
    )
    db.commit()
    return EdgeKeyOut(edge_key=edge_key)


@router.post("/{site_id}/pos/import", response_model=ImportReportOut)
def import_pos_csv(
    site_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportReportOut:
    """Import a POS CSV export. Re-importing the same file changes nothing (idempotent)."""
    site = get_site_for_user(db, user, site_id)
    content = file.file.read(settings.pos_import_max_bytes + 1)
    if len(content) > settings.pos_import_max_bytes:
        raise HTTPException(413, "file too large")

    adapter = CsvImportAdapter(max_rows=settings.pos_import_max_rows)
    try:
        parsed = adapter.parse(content, site_id=site_id, tz=ZoneInfo(site.timezone))
    except PosImportError as exc:
        raise HTTPException(422, str(exc)) from None

    report = import_sales(
        db,
        site_id,
        parsed.sales,
        source=adapter.name,
        rows_received=parsed.rows_received,
        errors=parsed.errors,
        checksum=hashlib.sha256(content).hexdigest(),
    )
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="pos.import",
        site_id=site_id,
        target_type="pos_import_batch",
        target_id=str(report.batch_id),
        detail={"inserted": report.inserted, "updated": report.updated, "rejected": report.rejected},
    )
    db.commit()
    return ImportReportOut(
        batch_id=report.batch_id,
        rows_received=report.rows_received,
        rows_inserted=report.inserted,
        rows_updated=report.updated,
        rows_unchanged=report.unchanged,
        rows_rejected=report.rejected,
        errors=[RowErrorOut(row=e.row, message=e.message) for e in report.errors],
        unmapped=report.unmapped,
        status_changes=report.status_changes,
        earliest=report.earliest,
        latest=report.latest,
    )


@router.get("/{site_id}/pos/imports", response_model=list[ImportBatchOut])
def list_imports(site_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_site_for_user(db, user, site_id)
    return (
        db.execute(
            select(PosImportBatch)
            .where(PosImportBatch.site_id == site_id)
            .order_by(PosImportBatch.started_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
