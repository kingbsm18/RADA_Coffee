"""Live notifications to dashboards (WebSocket hub) and the strong-alert decision.

Rule R12: every anomaly is stored and visible; only alerts flagged ``strong`` (gap
clearly above the café's measured noise level) should trigger a notification.
The hub is in-memory: it serves a single backend process (fine for the MVP; use a
shared broker only when running several workers).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.models.alert import Alert

logger = logging.getLogger("rada.notification")


class ConnectionHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, site_id: str, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        self._subscribers[site_id].add(websocket)

    def disconnect(self, site_id: str, websocket: WebSocket) -> None:
        self._subscribers[site_id].discard(websocket)
        if not self._subscribers[site_id]:
            self._subscribers.pop(site_id, None)

    def subscriber_count(self, site_id: str) -> int:
        return len(self._subscribers.get(site_id, ()))

    async def broadcast(self, site_id: str, message: dict[str, Any]) -> None:
        for websocket in list(self._subscribers.get(site_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:  # dead connection: drop it, never break the caller
                self.disconnect(site_id, websocket)

    def publish(self, site_id: str, message: dict[str, Any]) -> None:
        """Thread-safe entry point for sync code (request threads, the scheduler)."""
        loop = self._loop
        if loop is None or loop.is_closed() or not self._subscribers.get(site_id):
            return
        future = asyncio.run_coroutine_threadsafe(self.broadcast(site_id, message), loop)
        future.add_done_callback(_log_failure)


def _log_failure(future: Any) -> None:
    if future.exception() is not None:
        logger.warning("websocket broadcast failed: %s", future.exception())


hub = ConnectionHub()


def alert_message(kind: str, alert: Alert) -> dict[str, Any]:
    """Minimal payload: no photos, no personal data."""
    return {
        "type": kind,
        "alert": {
            "id": str(alert.id),
            "site_id": alert.site_id,
            "category": alert.category,
            "subtype": alert.subtype,
            "missing_qty": alert.missing_qty,
            "loss_est": str(alert.loss_est),
            "status": alert.status,
            "strong": alert.strong,
            "created_at": alert.created_at.isoformat(),
        },
    }


def notify_alert_created(alert: Alert) -> None:
    hub.publish(alert.site_id, alert_message("alert_created", alert))
    if alert.strong:
        logger.info("strong alert %s on site %s (%s)", alert.id, alert.site_id, alert.category)


def notify_alert_updated(alert: Alert) -> None:
    hub.publish(alert.site_id, alert_message("alert_updated", alert))
