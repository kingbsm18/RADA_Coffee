"""Local-disk snapshot storage (dev, local and edge-adjacent modes)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.infra.storage import InvalidSnapshotRef, SnapshotTooLarge, validate_ref


class LocalStorage:
    def __init__(self, base_dir: str | Path, *, max_bytes: int) -> None:
        self._base = Path(base_dir).resolve()
        self._max_bytes = max_bytes

    def _path(self, site_id: str, ref: str) -> Path:
        validate_ref(site_id)
        validate_ref(ref)
        path = (self._base / site_id / ref).resolve()
        # Defense in depth on top of validate_ref (e.g. symlinks).
        if self._base not in path.parents:
            raise InvalidSnapshotRef("invalid snapshot reference")
        return path

    def save(self, site_id: str, ref: str, data: bytes) -> bool:
        if len(data) > self._max_bytes:
            raise SnapshotTooLarge("snapshot too large")
        path = self._path(site_id, ref)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename: readers never see half-written images.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True

    def read(self, site_id: str, ref: str) -> bytes | None:
        path = self._path(site_id, ref)
        return path.read_bytes() if path.is_file() else None

    def exists(self, site_id: str, ref: str) -> bool:
        return self._path(site_id, ref).is_file()

    def delete(self, site_id: str, ref: str) -> None:
        self._path(site_id, ref).unlink(missing_ok=True)
