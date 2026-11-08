"""Snapshot storage interface and factory (local disk or S3)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Protocol

from app.config import settings

# Snapshot refs look like "snap/2026-11-05/104213_cam1.jpg".
_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


class StorageError(Exception):
    pass


class InvalidSnapshotRef(StorageError):
    pass


class SnapshotTooLarge(StorageError):
    pass


def validate_ref(ref: str) -> str:
    """Reject anything that could escape the storage root (traversal, absolute paths)."""
    if (
        not _REF_PATTERN.fullmatch(ref)
        or ref.endswith("/")
        or any(part in ("", ".", "..") for part in ref.split("/"))
    ):
        raise InvalidSnapshotRef("invalid snapshot reference")
    return ref


class Storage(Protocol):
    def save(self, site_id: str, ref: str, data: bytes) -> bool:
        """Store ``data``; return False (and keep the old file) if it already exists."""

    def read(self, site_id: str, ref: str) -> bytes | None: ...

    def exists(self, site_id: str, ref: str) -> bool: ...

    def delete(self, site_id: str, ref: str) -> None: ...


@lru_cache
def get_storage() -> Storage:
    if settings.storage_backend == "local":
        from app.infra.storage_local import LocalStorage

        return LocalStorage(settings.snapshot_dir, max_bytes=settings.snapshot_max_bytes)
    if settings.storage_backend == "s3":
        from app.infra.storage_s3 import S3Storage

        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3Storage(
            settings.s3_bucket, prefix=settings.s3_prefix, max_bytes=settings.snapshot_max_bytes
        )
    raise StorageError(f"unknown STORAGE_BACKEND: {settings.storage_backend!r}")
