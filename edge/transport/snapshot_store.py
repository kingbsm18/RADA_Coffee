"""edge/transport/snapshot_store.py — TODO: implement (see docs/architecture.md)."""
"""Safe local snapshot access for edge transport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class SnapshotStoreError(RuntimeError):
    """Raised when a snapshot cannot be accessed safely."""


class SnapshotStore:
    """Read and manage snapshots produced by SnapshotManager.

    References are relative paths such as:
    snapshots/site-01/cam-1/2026/11/08/<event-id>.jpg
    """

    def __init__(
        self,
        root: str | Path = "./data",
        *,
        max_bytes: int = 10_000_000,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive.")

        self.root = Path(root).expanduser().resolve()
        self.max_bytes = int(max_bytes)
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, snapshot_ref: str) -> Path:
        """Resolve a relative reference while preventing path traversal."""

        if not isinstance(snapshot_ref, str) or not snapshot_ref.strip():
            raise SnapshotStoreError("snapshot_ref must be a non-empty string.")

        if "\\" in snapshot_ref:
            raise SnapshotStoreError("Backslashes are not allowed in snapshot_ref.")

        relative = Path(snapshot_ref)

        if relative.is_absolute() or ".." in relative.parts:
            raise SnapshotStoreError("Invalid snapshot_ref path.")

        resolved = (self.root / relative).resolve()

        if not resolved.is_relative_to(self.root):
            raise SnapshotStoreError("Snapshot path escapes the storage root.")

        return resolved

    def exists(self, snapshot_ref: str) -> bool:
        """Return True when the referenced snapshot exists."""

        try:
            return self.resolve(snapshot_ref).is_file()
        except (OSError, SnapshotStoreError):
            return False

    def read(self, snapshot_ref: str) -> bytes:
        """Read a snapshot and enforce its configured size limit."""

        path = self.resolve(snapshot_ref)

        if not path.is_file():
            raise FileNotFoundError(snapshot_ref)

        size = path.stat().st_size
        if size <= 0:
            raise SnapshotStoreError("Snapshot file is empty.")

        if size > self.max_bytes:
            raise SnapshotStoreError(
                f"Snapshot exceeds the {self.max_bytes}-byte limit."
            )

        data = path.read_bytes()

        if not data.startswith(b"\xff\xd8\xff"):
            raise SnapshotStoreError("Snapshot is not a valid JPEG file.")

        return data

    def delete(self, snapshot_ref: str) -> bool:
        """Delete a local snapshot. Returns False if it does not exist."""

        path = self.resolve(snapshot_ref)

        if not path.is_file():
            return False

        path.unlink()
        return True

    def size(self, snapshot_ref: str) -> int:
        """Return the snapshot size in bytes."""

        path = self.resolve(snapshot_ref)

        if not path.is_file():
            raise FileNotFoundError(snapshot_ref)

        return path.stat().st_size


def create_snapshot_store(config: Mapping[str, Any]) -> SnapshotStore:
    """Create local snapshot access from edge configuration."""

    section = config.get("snapshot", {})
    if not isinstance(section, Mapping):
        raise ValueError("Invalid snapshot configuration.")

    return SnapshotStore(
        root=section.get("root", "./data"),
        max_bytes=int(section.get("max_bytes", 10_000_000)),
    )
