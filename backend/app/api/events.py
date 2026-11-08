"""Visual events: ingestion from the edge (idempotent) and dashboard listing."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import pagination, require_aware
from app.config import settings
from app.database import get_db
from app.models.category import Category
from app.models.detection import DETECTION_STATES, Detection
from app.models.org_site import Camera, User
from app.schemas.events import EventIngestResult, EventOut, EventPage, VisualEventIn
from app.security import edge_key_header, get_current_user, get_site_for_user, verify_edge_key

router = APIRouter(prefix="/events", tags=["events"])


def _same_event(row: Detection, payload: VisualEventIn) -> bool:
    return (
        row.camera_id == payload.camera_id
        and row.timestamp == payload.timestamp.astimezone(timezone.utc)
        and row.category == payload.category
        and row.count == payload.count
        and math.isclose(row.confidence, payload.confidence, abs_tol=1e-9)
        and row.snapshot_ref == payload.snapshot_ref
        and row.model_version == payload.model_version
    )


def _find(db: Session, site_id: str, event_id: str) -> Detection | None:
    return db.execute(
        select(Detection).where(Detection.site_id == site_id, Detection.event_id == event_id)
    ).scalar_one_or_none()


@router.post("", response_model=EventIngestResult, status_code=status.HTTP_201_CREATED)
def ingest_event(
    payload: VisualEventIn,
    response: Response,
    db: Session = Depends(get_db),
    edge_key: str | None = Depends(edge_key_header),
) -> EventIngestResult:
    """Edge -> backend. Re-sending the same event is a harmless 200 (outbox retries)."""
    verify_edge_key(db, payload.site_id, edge_key)

    latest_allowed = datetime.now(timezone.utc) + timedelta(seconds=settings.max_future_skew_seconds)
    if payload.timestamp > latest_allowed:
        raise HTTPException(
            422,
            "timestamp is in the future (check the edge clock / NTP)",
        )

    categories = set(
        db.execute(
            select(Category.name).where(
                Category.site_id == payload.site_id, Category.active.is_(True)
            )
        ).scalars()
    )
    if payload.category not in categories:
        raise HTTPException(
            422, f"unknown category: {payload.category!r}"
        )

    event_id = str(payload.event_id)

    def duplicate_or_conflict(row: Detection) -> EventIngestResult:
        if not _same_event(row, payload):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "event_id already used with different content"
            )
        response.status_code = status.HTTP_200_OK
        return EventIngestResult(status="duplicate", id=row.id)

    existing = _find(db, payload.site_id, event_id)
    if existing is not None:
        return duplicate_or_conflict(existing)

    detection = Detection(
        site_id=payload.site_id,
        event_id=event_id,
        camera_id=payload.camera_id,
        timestamp=payload.timestamp.astimezone(timezone.utc),
        category=payload.category,
        count=payload.count,
        confidence=payload.confidence,
        snapshot_ref=payload.snapshot_ref,
        model_version=payload.model_version,
    )
    db.add(detection)

    camera = db.execute(
        select(Camera).where(Camera.site_id == payload.site_id, Camera.camera_id == payload.camera_id)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if camera is None:
        db.add(Camera(site_id=payload.site_id, camera_id=payload.camera_id, last_seen_at=now))
    else:
        camera.last_seen_at = now

    try:
        db.commit()
    except IntegrityError:
        # A concurrent request inserted the same event first.
        db.rollback()
        existing = _find(db, payload.site_id, event_id)
        if existing is None:
            raise
        return duplicate_or_conflict(existing)
    return EventIngestResult(status="created", id=detection.id)


@router.get("", response_model=EventPage)
def list_events(
    site_id: str,
    category: str | None = None,
    state: str | None = Query(default=None, pattern="^[a-z_]+$"),
    since: datetime | None = None,
    until: datetime | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EventPage:
    get_site_for_user(db, user, site_id)
    if state is not None and state not in DETECTION_STATES:
        raise HTTPException(422, "unknown state")
    since, until = require_aware(since, "since"), require_aware(until, "until")

    conditions = [Detection.site_id == site_id]
    if category:
        conditions.append(Detection.category == category)
    if state:
        conditions.append(Detection.state == state)
    if since:
        conditions.append(Detection.timestamp >= since)
    if until:
        conditions.append(Detection.timestamp < until)

    limit, offset = page
    total = db.execute(select(func.count()).select_from(Detection).where(*conditions)).scalar_one()
    rows = db.execute(
        select(Detection)
        .where(*conditions)
        .order_by(Detection.timestamp.desc(), Detection.id)
        .limit(limit)
        .offset(offset)
    ).scalars()
    return EventPage(items=[EventOut.model_validate(r) for r in rows], total=total)
