"""app/infra/storage_local.py — TODO: implement (see docs/architecture.md)."""

"""Local filesystem implementation for RADA snapshot storage.

This module handles image persistence on the local filesystem.

It does not depend on FastAPI, SQLAlchemy or the reconciliation engine.
Snapshot references are opaque filenames, not arbitrary filesystem paths.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4


ALLOWED_IMAGE_EXTENSIONS = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
})


class LocalSnapshotStorage:
    """Store and retrieve image snapshots from a local directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        if not self.root.is_dir():
            raise NotADirectoryError(
                f"Snapshot storage root is not a directory: {self.root}"
            )

    @staticmethod
    def _validate_extension(extension: str) -> str:
        if not isinstance(extension, str):
            raise TypeError("Image extension must be a string")

        extension = extension.lower()

        if not extension.startswith("."):
            extension = f".{extension}"

        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Unsupported image extension: {extension!r}"
            )

        return extension

    def _resolve_ref(self, snapshot_ref: str) -> Path:
        """Validate a snapshot reference and resolve it inside root."""
        if not isinstance(snapshot_ref, str) or not snapshot_ref.strip():
            raise ValueError("snapshot_ref cannot be empty")

        if (
            "/" in snapshot_ref
            or "\\" in snapshot_ref
            or snapshot_ref in {".", ".."}
        ):
            raise ValueError("Invalid snapshot reference")

        path = (self.root / snapshot_ref).resolve()

        if path.parent != self.root:
            raise ValueError("Snapshot reference escapes storage directory")

        if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("Unsupported snapshot file extension")

        return path

    def put(
        self,
        content: bytes,
        extension: str = ".jpg",
    ) -> str:
        """Atomically save an image and return its snapshot reference."""
        if not isinstance(content, bytes):
            raise TypeError("Snapshot content must be bytes")

        if not content:
            raise ValueError("Snapshot content cannot be empty")

        suffix = self._validate_extension(extension)
        snapshot_ref = f"{uuid4().hex}{suffix}"
        destination = self._resolve_ref(snapshot_ref)

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.root,
                prefix=".snapshot-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                temporary_path = Path(temporary_file.name)

            temporary_path.replace(destination)

        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

        return snapshot_ref

    def get(self, snapshot_ref: str) -> bytes:
        """Retrieve an image by its snapshot reference."""
        path = self._resolve_ref(snapshot_ref)

        if not path.is_file():
            raise FileNotFoundError(
                f"Snapshot not found: {snapshot_ref}"
            )

        return path.read_bytes()

    def delete(self, snapshot_ref: str) -> bool:
        """Delete an image. Return False if it does not exist."""
        path = self._resolve_ref(snapshot_ref)

        if not path.exists():
            return False

        if not path.is_file():
            raise ValueError("Snapshot reference is not a file")

        path.unlink()
        return True
