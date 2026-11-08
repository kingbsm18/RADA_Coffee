"""S3 snapshot storage (hybrid/cloud modes).

Needs ``boto3`` (``pip install -e ".[s3]"``). NOT yet tested against a real bucket:
the unit tests only exercise it with a fake client.
"""

from __future__ import annotations

from typing import Any

from app.infra.storage import SnapshotTooLarge, StorageError, validate_ref


class S3Storage:
    def __init__(
        self, bucket: str, *, prefix: str = "snapshots", max_bytes: int, client: Any = None
    ) -> None:
        if client is None:
            try:
                import boto3  # imported lazily: optional dependency
            except ImportError as exc:  # pragma: no cover
                raise StorageError("boto3 is required for STORAGE_BACKEND=s3") from exc
            client = boto3.client("s3")
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._max_bytes = max_bytes

    def _key(self, site_id: str, ref: str) -> str:
        validate_ref(site_id)
        validate_ref(ref)
        return f"{self._prefix}/{site_id}/{ref}" if self._prefix else f"{site_id}/{ref}"

    def exists(self, site_id: str, ref: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(site_id, ref))
            return True
        except Exception as exc:  # botocore ClientError with a 404 code
            if _is_not_found(exc):
                return False
            raise

    def save(self, site_id: str, ref: str, data: bytes) -> bool:
        if len(data) > self._max_bytes:
            raise SnapshotTooLarge("snapshot too large")
        if self.exists(site_id, ref):
            return False
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(site_id, ref),
            Body=data,
            ServerSideEncryption="AES256",
        )
        return True

    def read(self, site_id: str, ref: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._key(site_id, ref))
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        return response["Body"].read()

    def delete(self, site_id: str, ref: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(site_id, ref))


def _is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}
