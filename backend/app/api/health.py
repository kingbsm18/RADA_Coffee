from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app import database

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up (no dependency checks)."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    """Readiness: the database answers."""
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from None
    return {"status": "ready"}
