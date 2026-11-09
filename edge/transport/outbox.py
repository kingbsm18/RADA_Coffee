"""SQLite-backed persistent outbox for visual events."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class OutboxError(RuntimeError):
    """Raised when an outbox operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class OutboxItem:
    event_id: str
    payload: dict[str, Any]
    attempts: int
    created_at: datetime
    next_attempt_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxStats:
    pending: int
    sent: int
    dead: int
    total: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 string.")

    normalized = value.strip().replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must be a valid ISO 8601 date-time.") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset.")

    return parsed.astimezone(timezone.utc)


def validate_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the visual_event.v1 payload."""

    if not isinstance(payload, Mapping):
        raise ValueError("Event payload must be a mapping.")

    required = {
        "schema",
        "event_id",
        "site_id",
        "camera_id",
        "timestamp",
        "category",
        "count",
        "confidence",
        "model_version",
    }

    allowed = required | {"snapshot_ref"}

    missing = required - set(payload)
    unknown = set(payload) - allowed

    if missing:
        raise ValueError(f"Missing event fields: {sorted(missing)}")

    if unknown:
        raise ValueError(f"Unknown event fields: {sorted(unknown)}")

    event = dict(payload)

    if event["schema"] != "visual_event.v1":
        raise ValueError("Unsupported event schema.")

    try:
        event["event_id"] = str(uuid.UUID(str(event["event_id"])))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("event_id must be a valid UUID.") from exc

    site_id = event["site_id"]
    if not isinstance(site_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", site_id
    ):
        raise ValueError("Invalid site_id.")

    camera_id = event["camera_id"]
    if not isinstance(camera_id, str) or not 1 <= len(camera_id) <= 64:
        raise ValueError("camera_id must contain between 1 and 64 characters.")

    category = event["category"]
    if not isinstance(category, str) or not 1 <= len(category) <= 64:
        raise ValueError("category must contain between 1 and 64 characters.")

    count = event["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("count must be an integer between 1 and 100.")

    confidence = event["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric.")

    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1.")

    model_version = event["model_version"]
    if not isinstance(model_version, str) or not 1 <= len(model_version) <= 64:
        raise ValueError("model_version must contain between 1 and 64 characters.")

    snapshot_ref = event.get("snapshot_ref")
    if snapshot_ref is not None:
        if not isinstance(snapshot_ref, str) or len(snapshot_ref) > 255:
            raise ValueError("snapshot_ref must be null or a string of at most 255 characters.")

    # Keep the original event timestamp and its UTC offset.
    _timestamp(event["timestamp"])

    event["confidence"] = confidence
    event.setdefault("snapshot_ref", None)

    return event


class Outbox:
    """Durable SQLite queue for edge events.

    States:
      pending: waiting for delivery or retry
      sent: acknowledged by the backend
      dead: permanent delivery or authentication error
    """

    def __init__(
        self,
        path: str | Path = "./outbox.db",
        *,
        timeout: float = 10.0,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._closed = False

        try:
            self._connection = sqlite3.connect(
                str(self.path),
                timeout=self.timeout,
                check_same_thread=False,
                isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
        except sqlite3.Error as exc:
            raise OutboxError(f"Could not initialize outbox: {exc}") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise OutboxError("Outbox is closed.")

    def _create_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_outbox (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'sent', 'dead')),
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                next_attempt_at REAL NOT NULL,
                sent_at REAL,
                last_error TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_edge_outbox_pending
            ON edge_outbox(status, next_attempt_at, created_at)
            """
        )

    def enqueue(self, payload: Mapping[str, Any]) -> bool:
        """Persist an event.

        Returns True if inserted, False if the identical event already exists.
        Reusing an event_id with different content raises OutboxError.
        """

        event = validate_event_payload(payload)
        event_id = event["event_id"]
        serialized = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        now = _utc_now().timestamp()

        with self._lock:
            self._ensure_open()

            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    "SELECT payload_json FROM edge_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()

                if existing is not None:
                    self._connection.execute("ROLLBACK")
                    if existing["payload_json"] != serialized:
                        raise OutboxError(
                            f"event_id {event_id} already exists with different content."
                        )
                    return False

                self._connection.execute(
                    """
                    INSERT INTO edge_outbox (
                        event_id, payload_json, status, attempts,
                        created_at, next_attempt_at
                    )
                    VALUES (?, ?, 'pending', 0, ?, ?)
                    """,
                    (event_id, serialized, now, now),
                )
                self._connection.execute("COMMIT")
                return True

            except OutboxError:
                raise
            except sqlite3.Error as exc:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise OutboxError(f"Could not enqueue event: {exc}") from exc

    def get_pending(self, limit: int = 50) -> list[OutboxItem]:
        """Return due events in FIFO order without removing them."""

        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer.")

        now = _utc_now().timestamp()

        with self._lock:
            self._ensure_open()
            try:
                rows = self._connection.execute(
                    """
                    SELECT event_id, payload_json, attempts,
                           created_at, next_attempt_at
                    FROM edge_outbox
                    WHERE status = 'pending' AND next_attempt_at <= ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (now, int(limit)),
                ).fetchall()
            except sqlite3.Error as exc:
                raise OutboxError(f"Could not read pending events: {exc}") from exc

        return [
            OutboxItem(
                event_id=row["event_id"],
                payload=json.loads(row["payload_json"]),
                attempts=int(row["attempts"]),
                created_at=datetime.fromtimestamp(
                    row["created_at"], tz=timezone.utc
                ),
                next_attempt_at=datetime.fromtimestamp(
                    row["next_attempt_at"], tz=timezone.utc
                ),
            )
            for row in rows
        ]

    def mark_sent(self, event_id: str) -> None:
        """Mark an event as acknowledged by the backend."""

        self._update(
            event_id,
            """
            UPDATE edge_outbox
            SET status = 'sent', sent_at = ?, last_error = NULL
            WHERE event_id = ? AND status != 'sent'
            """,
            (_utc_now().timestamp(), str(event_id)),
        )

    def mark_failed(
        self,
        event_id: str,
        *,
        error: str,
        retry_after_seconds: float,
        permanent: bool = False,
    ) -> None:
        """Record a failed attempt and schedule a retry or mark it dead."""

        delay = max(0.0, float(retry_after_seconds))
        status = "dead" if permanent else "pending"
        now = _utc_now().timestamp()

        self._update(
            event_id,
            """
            UPDATE edge_outbox
            SET status = ?,
                attempts = attempts + 1,
                next_attempt_at = ?,
                last_error = ?
            WHERE event_id = ? AND status = 'pending'
            """,
            (
                status,
                now + delay,
                str(error)[:2000],
                str(event_id),
            ),
        )

    def _update(self, event_id: str, query: str, values: tuple[Any, ...]) -> None:
        with self._lock:
            self._ensure_open()
            try:
                cursor = self._connection.execute(query, values)
                if cursor.rowcount == 0:
                    exists = self._connection.execute(
                        "SELECT 1 FROM edge_outbox WHERE event_id = ?",
                        (str(event_id),),
                    ).fetchone()
                    if exists is None:
                        raise OutboxError(f"Unknown event_id: {event_id}")
            except OutboxError:
                raise
            except sqlite3.Error as exc:
                raise OutboxError(f"Could not update event {event_id}: {exc}") from exc

    def stats(self) -> OutboxStats:
        """Return queue counters."""

        with self._lock:
            self._ensure_open()
            try:
                rows = self._connection.execute(
                    "SELECT status, COUNT(*) AS total FROM edge_outbox GROUP BY status"
                ).fetchall()
            except sqlite3.Error as exc:
                raise OutboxError(f"Could not read outbox stats: {exc}") from exc

        counts = {row["status"]: int(row["total"]) for row in rows}
        pending = counts.get("pending", 0)
        sent = counts.get("sent", 0)
        dead = counts.get("dead", 0)

        return OutboxStats(
            pending=pending,
            sent=sent,
            dead=dead,
            total=pending + sent + dead,
        )

    def requeue_dead(self, event_id: str | None = None) -> int:
        """Manually requeue dead events after fixing the underlying problem."""

        with self._lock:
            self._ensure_open()
            try:
                if event_id is None:
                    cursor = self._connection.execute(
                        """
                        UPDATE edge_outbox
                        SET status = 'pending', next_attempt_at = ?,
                            last_error = NULL
                        WHERE status = 'dead'
                        """,
                        (_utc_now().timestamp(),),
                    )
                else:
                    cursor = self._connection.execute(
                        """
                        UPDATE edge_outbox
                        SET status = 'pending', next_attempt_at = ?,
                            last_error = NULL
                        WHERE status = 'dead' AND event_id = ?
                        """,
                        (_utc_now().timestamp(), str(event_id)),
                    )
                return int(cursor.rowcount)
            except sqlite3.Error as exc:
                raise OutboxError(f"Could not requeue dead events: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "Outbox":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def create_outbox(config: Mapping[str, Any]) -> Outbox:
    """Create the outbox from edge/config.yaml."""

    transport = config.get("transport", {})
    if not isinstance(transport, Mapping):
        raise ValueError("Invalid transport configuration.")

    return Outbox(
        path=transport.get("outbox_path", "./outbox.db"),
        timeout=float(transport.get("sqlite_timeout", 10.0)),
    )
