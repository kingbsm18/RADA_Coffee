"""Live alert stream. The token is sent as the FIRST message, never in the URL
(URLs end up in access logs)."""

from __future__ import annotations

import asyncio
import json
import uuid

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.org_site import Site, User
from app.security import decode_access_token
from app.services.notification import hub

router = APIRouter(tags=["websocket"])
AUTH_TIMEOUT_SECONDS = 5
POLICY_VIOLATION = 1008


def _may_listen(db: Session, claims: dict, site_id: str) -> bool:
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.active:
        return False
    site = db.execute(
        select(Site).where(Site.id == site_id, Site.org_id == user.org_id)
    ).scalar_one_or_none()
    return site is not None


@router.websocket("/ws/alerts")
async def alerts_stream(websocket: WebSocket, site_id: str, db: Session = Depends(get_db)) -> None:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        claims = decode_access_token(json.loads(raw)["token"])
        allowed = await run_in_threadpool(_may_listen, db, claims, site_id)
    except (asyncio.TimeoutError, WebSocketDisconnect, jwt.PyJWTError, ValueError, KeyError, TypeError):
        allowed = False
    finally:
        db.close()  # never hold a pooled connection for the lifetime of the socket

    if not allowed:
        await websocket.close(code=POLICY_VIOLATION)
        return

    await hub.connect(site_id, websocket)  # subscribe first: nothing published after "ready" is lost
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            await websocket.receive_text()  # ignore content; raises on disconnect
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(site_id, websocket)
