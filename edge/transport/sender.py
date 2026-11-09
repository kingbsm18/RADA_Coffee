"""HTTP sender for persistent visual-event delivery."""

from __future__ import annotations

import os
import random
import time

from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .outbox import Outbox, OutboxError, OutboxItem


class SenderError(RuntimeError):
    """Raised when the event sender is incorrectly configured."""


@dataclass(frozen=True, slots=True)
class SendResult:
    sent: int
    retried: int
    dead: int
    remaining: int


class EventSender:
    """Deliver outbox events to the RADA backend.

    The sender never deletes an event before the backend acknowledges it.
    HTTP 200 and 201 are successful acknowledgements.
    """

    def __init__(
        self,
        *,
        outbox: Outbox,
        backend_url: str,
        edge_key: str,
        endpoint: str = "/events",
        timeout: float = 10.0,
        batch_size: int = 50,
        max_backoff_seconds: float = 300.0,
        verify_tls: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        if not backend_url or not backend_url.strip():
            raise SenderError("backend_url is required.")

        if not edge_key or not edge_key.strip():
            raise SenderError("Edge API key is required.")

        if timeout <= 0:
            raise SenderError("timeout must be positive.")

        if batch_size < 1:
            raise SenderError("batch_size must be positive.")

        if max_backoff_seconds <= 0:
            raise SenderError("max_backoff_seconds must be positive.")

        self.outbox = outbox
        self.base_url = backend_url.rstrip("/")
        self.endpoint = "/" + endpoint.strip("/")
        self.edge_key = edge_key.strip()
        self.timeout = float(timeout)
        self.batch_size = int(batch_size)
        self.max_backoff_seconds = float(max_backoff_seconds)

        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=self.timeout,
            verify=verify_tls,
            headers={
                "X-Edge-Key": self.edge_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def _retry_delay(self, attempts: int) -> float:
        """Exponential backoff with jitter, capped to avoid endless long waits."""

        exponent = min(max(attempts, 0), 16)
        base = min(2.0 ** exponent, self.max_backoff_seconds)
        return min(
            self.max_backoff_seconds,
            base * random.uniform(0.8, 1.2),
        )

    @staticmethod
    def _is_permanent_http_error(status_code: int) -> bool:
        # Authentication, authorization, and validation errors need operator action.
        if status_code in (400, 401, 403, 404, 409, 422):
            return True
        return 400 <= status_code < 500 and status_code not in (408, 425, 429)

    def _deliver(self, item: OutboxItem) -> str:
        url = f"{self.base_url}{self.endpoint}"

        response = self.client.post(url, json=item.payload)

        if response.status_code in (200, 201):
            try:
                body = response.json()
            except ValueError as exc:
                raise SenderError(
                    "Backend returned success without a valid JSON acknowledgement."
                ) from exc

            if body.get("status") not in ("created", "duplicate"):
                raise SenderError("Unexpected backend acknowledgement.")

            return str(body["status"])

        message = response.text[:1000] if response.text else "No response body."
        raise httpx.HTTPStatusError(
            f"Backend returned HTTP {response.status_code}: {message}",
            request=response.request,
            response=response,
        )

    def send_pending(self, limit: int | None = None) -> SendResult:
        """Attempt to deliver currently due events."""

        selected_limit = self.batch_size if limit is None else int(limit)
        if selected_limit < 1:
            raise ValueError("limit must be positive.")

        try:
            items = self.outbox.get_pending(selected_limit)
        except OutboxError:
            raise

        sent = 0
        retried = 0
        dead = 0

        for item in items:
            try:
                self._deliver(item)
                self.outbox.mark_sent(item.event_id)
                sent += 1

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                permanent = self._is_permanent_http_error(status_code)

                self.outbox.mark_failed(
                    item.event_id,
                    error=str(exc),
                    retry_after_seconds=(
                        0.0 if permanent else self._retry_delay(item.attempts)
                    ),
                    permanent=permanent,
                )

                if permanent:
                    dead += 1
                else:
                    retried += 1

                # Stop this batch on authentication or server availability failures.
                if status_code in (401, 403, 408, 425, 429) or status_code >= 500:
                    break

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self.outbox.mark_failed(
                    item.event_id,
                    error=str(exc),
                    retry_after_seconds=self._retry_delay(item.attempts),
                    permanent=False,
                )
                retried += 1
                # A network outage is likely to affect the rest of the batch too.
                break

            except SenderError as exc:
                self.outbox.mark_failed(
                    item.event_id,
                    error=str(exc),
                    retry_after_seconds=0.0,
                    permanent=True,
                )
                dead += 1

        remaining = self.outbox.stats().pending

        return SendResult(
            sent=sent,
            retried=retried,
            dead=dead,
            remaining=remaining,
        )

    def run_once(self) -> SendResult:
        """Alias useful for a scheduler or a worker loop."""

        return self.send_pending()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "EventSender":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def create_sender(
    config: Mapping[str, Any],
    outbox: Outbox,
) -> EventSender:
    """Create the HTTP sender from edge configuration and environment."""

    transport = config.get("transport", {})
    if not isinstance(transport, Mapping):
        raise ValueError("Invalid transport configuration.")

    backend_url = str(transport.get("backend_url", "")).strip()
    edge_key_env = str(transport.get("edge_key_env", "RADA_EDGE_KEY")).strip()
    edge_key = os.getenv(edge_key_env, "").strip()

    return EventSender(
        outbox=outbox,
        backend_url=backend_url,
        edge_key=edge_key,
        endpoint=str(transport.get("events_endpoint", "/events")),
        timeout=float(transport.get("timeout", 10.0)),
        batch_size=int(transport.get("batch_size", 50)),
        max_backoff_seconds=float(
            transport.get("max_backoff_seconds", 300.0)
        ),
        verify_tls=bool(transport.get("verify_tls", True)),
    )
