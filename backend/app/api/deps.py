"""Small shared request helpers (pagination, timezone-aware query parameters)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, Query


def pagination(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000)
) -> tuple[int, int]:
    return limit, offset


def require_aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(
            422, f"{name} must include a UTC offset (e.g. Z)"
        )
    return value
