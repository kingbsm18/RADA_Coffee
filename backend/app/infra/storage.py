"""app/infra/storage.py — TODO: implement (see docs/architecture.md)."""

"""Local snapshot storage for RADA Café Intelligence.

Stores image snapshots produced by the edge application.

Design:
- Local-first storage.
- No FastAPI or database dependency.
- Snapshot references are relative identifiers, never filesystem paths.
- Writes are atomic to avoid partially written snapshots.
- Only image extensions are accepted; video storage is not supported.

The application layer creates the storage adapter and passes it to services.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol
from uuid import uuid4


ALLOWED_IMAGE_EXTENSIONS = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
})


class SnapshotStorage(Protocol):
    """Interface implemented by snapshot storage backends."""

    def put(self, content: bytes, extension: str = ".jpg") -> str:
        """Store an image and return its reference."""
        ...

    def get(self, snapshot_ref: str) -> bytes:
        """Read an image using its reference."""
        ...

    def delete(self, snapshot_ref: str) -> bool:
        """Delete an image. Return False if it does not exist."""
        ...


class LocalSnapshotStorage:
    """Filesystem-based snapshot storage."""

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

        normalized = extension.lower()

        if not normalized.startswith("."):
            normalized = f".{normalized}"

        if normalized not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Unsupported image extension: {extension!r}"
            )

        return normalized

    def _resolve_ref(self, snapshot_ref: str) -> Path:
        """Resolve a reference safely inside the configured storage root."""
        if not isinstance(snapshot_ref, str) or not snapshot_ref.strip():
            raise ValueError("snapshot_ref cannot be empty")

        # References are generated identifiers, not arbitrary paths.
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
            raise ValueError("Snapshot reference has an unsupported extension")

        return path

    def put(
        self,
        content: bytes,
        extension: str = ".jpg",
    ) -> str:
        """Atomically store an image and return its relative reference."""
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
        """Return the stored image bytes."""
        path = self._resolve_ref(snapshot_ref)

        if not path.is_file():
            raise FileNotFoundError(
                f"Snapshot not found: {snapshot_ref}"
            )

        return path.read_bytes()

    def delete(self, snapshot_ref: str) -> bool:
        """Delete a stored image without failing if it is already absent."""
        path = self._resolve_ref(snapshot_ref)

        if not path.exists():
            return False

        if not path.is_file():
            raise ValueError("Snapshot reference does not point to a file")

        path.unlink()
        return True


def create_snapshot_storage(
    backend: str,
    snapshot_dir: str | Path,
) -> SnapshotStorage:
    """Create the configured snapshot storage backend.

    Only the local backend is implemented at this stage.
    """
    normalized_backend = backend.strip().lower()

    if normalized_backend == "local":
        return LocalSnapshotStorage(snapshot_dir)

    raise ValueError(
        f"Unsupported storage backend: {backend!r}. "
        "Currently supported: 'local'."
    )
