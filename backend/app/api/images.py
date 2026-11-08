"""Snapshots: upload from the edge, list and view for managers (every access is audited)."""

from __future__ import annotations

from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_aware
from app.config import settings
from app.database import get_db
from app.infra.storage import (
    InvalidSnapshotRef,
    SnapshotTooLarge,
    Storage,
    get_storage,
    validate_ref,
)
from app.models.audit import record_audit
from app.models.detection import Detection
from app.models.org_site import User
from app.security import edge_key_header, get_current_user, get_site_for_user, verify_edge_key

router = APIRouter(tags=["images"])


def sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class SnapshotUploadOut(BaseModel):
    status: str  # created | duplicate


class SnapshotItem(BaseModel):
    event_id: str
    timestamp: datetime
    category: str
    confidence: float
    state: str
    url: str


@router.post("/images", response_model=SnapshotUploadOut, status_code=status.HTTP_201_CREATED)
def upload_snapshot(
    response: Response,
    site_id: str = Form(...),
    snapshot_ref: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    edge_key: str | None = Depends(edge_key_header),
    storage: Storage = Depends(get_storage),
) -> SnapshotUploadOut:
    verify_edge_key(db, site_id, edge_key)
    try:
        validate_ref(snapshot_ref)
    except InvalidSnapshotRef:
        raise HTTPException(422, "invalid snapshot_ref") from None

    data = file.file.read(settings.snapshot_max_bytes + 1)
    if len(data) > settings.snapshot_max_bytes:
        raise HTTPException(413, "snapshot too large")
    if sniff_image_type(data) is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only JPEG, PNG or WebP images")

    try:
        created = storage.save(site_id, snapshot_ref, data)
    except SnapshotTooLarge:
        raise HTTPException(413, "snapshot too large") from None
    if not created:
        response.status_code = status.HTTP_200_OK  # outbox retry: already stored
    return SnapshotUploadOut(status="created" if created else "duplicate")


@router.get("/sites/{site_id}/images", response_model=list[SnapshotItem])
def list_snapshots(
    site_id: str,
    category: str,
    since: datetime,
    until: datetime,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SnapshotItem]:
    """All photos of a category in a period (R11): never one photo presented as THE proof."""
    get_site_for_user(db, user, site_id)
    since, until = require_aware(since, "since"), require_aware(until, "until")
    rows = db.execute(
        select(Detection)
        .where(
            Detection.site_id == site_id,
            Detection.category == category,
            Detection.snapshot_ref.is_not(None),
            Detection.timestamp >= since,
            Detection.timestamp < until,
        )
        .order_by(Detection.timestamp)
        .limit(limit)
    ).scalars()
    items = [
        SnapshotItem(
            event_id=row.event_id,
            timestamp=row.timestamp,
            category=row.category,
            confidence=row.confidence,
            state=row.state,
            url=f"/api/v1/images/{site_id}/{row.snapshot_ref}",
        )
        for row in rows
    ]
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="image.list",
        site_id=site_id,
        detail={"category": category, "count": len(items)},
    )
    db.commit()
    return items


@router.get("/images/{site_id}/{ref:path}")
def view_snapshot(
    site_id: str,
    ref: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> Response:
    get_site_for_user(db, user, site_id)
    try:
        data = storage.read(site_id, ref)
    except InvalidSnapshotRef:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid snapshot reference") from None
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")
    record_audit(
        db,
        actor_label=user.username,
        actor_user_id=user.id,
        action="image.view",
        site_id=site_id,
        target_type="snapshot",
        target_id=ref,
    )
    db.commit()
    return Response(
        content=data,
        media_type=sniff_image_type(data) or "application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
