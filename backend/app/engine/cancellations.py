"""app/engine/cancellations.py — TODO: implement (see docs/architecture.md)."""
"""Handle POS cancellations and refunds after service (business rule R8).

When a POS sale previously used to reconcile a visual detection becomes
voided or refunded, its credit must be unlinked and the affected detection
unit must become an anomaly with subtype ``cancelled_after_service``.

Pure module:
- No database access.
- No framework dependencies.
- No system clock.
- All inputs are explicitly provided by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.engine.finalize import AnomalyUnit
from app.engine.types import Credit, Detection, SaleRecord


@dataclass(frozen=True, slots=True)
class CancellationMatch:
    """A visual detection unit previously matched to a POS credit."""

    detection: Detection
    unit_index: int
    credit: Credit

    def __post_init__(self) -> None:
        if isinstance(self.unit_index, bool) or not isinstance(
            self.unit_index, int
        ):
            raise TypeError("unit_index must be an integer")

        if not 1 <= self.unit_index <= self.detection.count:
            raise ValueError(
                f"unit_index must be between 1 and "
                f"{self.detection.count}, got {self.unit_index}"
            )

        if self.detection.site_id != self.credit.site_id:
            raise ValueError(
                "Detection and credit must belong to the same site"
            )

        if self.detection.category != self.credit.category:
            raise ValueError(
                "Detection and credit must belong to the same category"
            )


@dataclass(frozen=True, slots=True)
class CancellationResult:
    """Result of processing a cancelled or refunded POS sale."""

    unlinked_credit_ids: tuple[str, ...]
    anomalies: tuple[AnomalyUnit, ...]


def handle_cancellation(
    sale: SaleRecord,
    matches: Iterable[CancellationMatch],
) -> CancellationResult:
    """Unlink credits from a cancelled/refunded sale and create anomalies.

    Only matches linked to the specified POS sale are affected.

    Rules:
    - Only ``voided`` and ``refunded`` sales are accepted.
    - Matching is isolated by site and POS sale ID.
    - Each affected detection unit becomes ``cancelled_after_service``.
    - Existing unrelated matches are left untouched.
    - Duplicate detection units or credit IDs are rejected.
    - Results are deterministic and safe to calculate repeatedly.

    The caller is responsible for persisting the unlinking and anomalies
    transactionally, and for ensuring the operation is idempotent.

    Note:
    This implements the current R8 reference algorithm: the affected unit
    immediately becomes an anomaly. It does not search for another free
    POS credit.
    """
    if sale.status not in {"voided", "refunded"}:
        raise ValueError(
            "Cancellation requires a sale with status "
            "'voided' or 'refunded'"
        )

    unique_matches: dict[tuple[str, int], CancellationMatch] = {}
    seen_credit_ids: set[str] = set()

    affected_matches: list[CancellationMatch] = []

    for match in matches:
        key = (match.detection.event_id, match.unit_index)

        existing = unique_matches.get(key)
        if existing is not None:
            raise ValueError(
                f"Duplicate detection unit in matches: {key!r}"
            )

        unique_matches[key] = match

        credit_id = match.credit.credit_id
        if credit_id in seen_credit_ids:
            raise ValueError(
                f"Credit {credit_id!r} is linked more than once"
            )

        seen_credit_ids.add(credit_id)

        if (
            match.credit.site_id == sale.site_id
            and match.credit.sale_id == sale.external_id
        ):
            affected_matches.append(match)

    # Oldest detections first, with deterministic tie-breakers.
    affected_matches.sort(
        key=lambda match: (
            match.detection.timestamp,
            match.detection.event_id,
            match.unit_index,
        )
    )

    anomalies = tuple(
        AnomalyUnit(
            detection=match.detection,
            unit_index=match.unit_index,
            subtype="cancelled_after_service",
            state="anomaly",
        )
        for match in affected_matches
    )

    unlinked_credit_ids = tuple(
        match.credit.credit_id for match in affected_matches
    )

    return CancellationResult(
        unlinked_credit_ids=unlinked_credit_ids,
        anomalies=anomalies,
    )
