"""app/infra/storage_s3.py — TODO: implement (see docs/architecture.md)."""

"""Amazon S3 implementation for RADA snapshot storage.

Stores image snapshots in a private S3 bucket.

The returned snapshot reference is an object key, not a public URL.
This module does not expose snapshots publicly.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from botocore.exceptions import ClientError

from app.infra.storage_local import ALLOWED_IMAGE_EXTENSIONS


CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class S3SnapshotStorage:
    """Store and retrieve image snapshots using Amazon S3."""

    def __init__(
        self,
        bucket: str,
        region_name: str | None = None,
        prefix: str = "snapshots",
        endpoint_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError("S3 bucket name cannot be empty")

        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.region_name = region_name
        self.endpoint_url = endpoint_url

        if client is not None:
            self.client = client
        else:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "S3 storage requires boto3. "
                    "Install it with: pip install boto3"
                ) from exc

            self.client = boto3.client(
                "s3",
                region_name=region_name,
                endpoint_url=endpoint_url,
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

    def _build_key(self, snapshot_ref: str) -> str:
        """Build an S3 object key from a safe snapshot reference."""
        if not isinstance(snapshot_ref, str) or not snapshot_ref.strip():
            raise ValueError("snapshot_ref cannot be empty")

        if (
            "/" in snapshot_ref
            or "\\" in snapshot_ref
            or snapshot_ref in {".", ".."}
        ):
            raise ValueError("Invalid snapshot reference")

        extension = "." + snapshot_ref.rsplit(".", 1)[-1].lower()

        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("Unsupported snapshot file extension")

        if self.prefix:
            return f"{self.prefix}/{snapshot_ref}"

        return snapshot_ref

    def put(
        self,
        content: bytes,
        extension: str = ".jpg",
    ) -> str:
        """Upload an image and return its snapshot reference."""
        if not isinstance(content, bytes):
            raise TypeError("Snapshot content must be bytes")

        if not content:
            raise ValueError("Snapshot content cannot be empty")

        suffix = self._validate_extension(extension)
        snapshot_ref = f"{uuid4().hex}{suffix}"
        key = self._build_key(snapshot_ref)

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=CONTENT_TYPES[suffix],
        )

        return snapshot_ref

    def get(self, snapshot_ref: str) -> bytes:
        """Download an image using its snapshot reference."""
        key = self._build_key(snapshot_ref)

        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=key,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(
                    f"Snapshot not found: {snapshot_ref}"
                ) from exc

            raise

        body = response["Body"]

        try:
            return body.read()
        finally:
            body.close()

    def delete(self, snapshot_ref: str) -> bool:
        """Delete an image. Return False if it does not exist."""
        key = self._build_key(snapshot_ref)

        try:
            self.client.head_object(
                Bucket=self.bucket,
                Key=key,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False

            raise

        self.client.delete_object(
            Bucket=self.bucket,
            Key=key,
        )

        return True
