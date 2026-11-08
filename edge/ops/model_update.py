"""Secure ONNX model updates for the RADA AI edge runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


class ModelUpdateError(RuntimeError):
    """Raised when a model update cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ModelUpdateResult:
    """Result of a model update operation."""

    status: str
    model_path: str
    version: str
    sha256: str
    size_bytes: int
    updated_at: str
    restart_required: bool
    backup_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent HTTPS downloads from redirecting to plain HTTP."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        parsed = urlparse(new_url)

        if parsed.scheme.lower() != "https":
            raise ModelUpdateError(
                "Model download redirect must remain HTTPS."
            )

        return super().redirect_request(
            request,
            response,
            code,
            message,
            headers,
            new_url,
        )


class ModelUpdater:
    """Download, verify, validate and atomically install ONNX models.

    The active model is not changed until the downloaded file passes
    SHA-256 verification and ONNX Runtime validation.

    A reload_callback can reload the detector after installation.
    Without one, the caller must restart/reload the inference process.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        backup_path: str | Path | None = None,
        manifest_path: str | Path | None = None,
        max_download_bytes: int = 2_000_000_000,
        timeout: float = 60.0,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()

        if self.model_path.suffix.lower() != ".onnx":
            raise ValueError("Only ONNX model files are supported.")

        if max_download_bytes <= 0:
            raise ValueError("max_download_bytes must be positive.")

        if timeout <= 0:
            raise ValueError("timeout must be positive.")

        self.backup_path = (
            Path(backup_path).expanduser().resolve()
            if backup_path
            else self.model_path.with_suffix(
                self.model_path.suffix + ".bak"
            )
        )

        self.manifest_path = (
            Path(manifest_path).expanduser().resolve()
            if manifest_path
            else self.model_path.with_suffix(".manifest.json")
        )

        if (
            self.model_path == self.backup_path
            or self.model_path == self.manifest_path
            or self.backup_path == self.manifest_path
        ):
            raise ValueError("Model, backup and manifest paths must differ.")

        self.max_download_bytes = int(max_download_bytes)
        self.timeout = float(timeout)

        self._lock = threading.RLock()

    @staticmethod
    def _validate_version(version: str) -> str:
        version = str(version).strip()

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", version):
            raise ValueError("Invalid model version.")

        return version

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme.lower() != "https":
            raise ModelUpdateError(
                "Model downloads require an HTTPS URL."
            )

        if not parsed.hostname:
            raise ModelUpdateError("Invalid model download URL.")

        if parsed.username or parsed.password:
            raise ModelUpdateError(
                "Credentials must not be embedded in the model URL."
            )

    @staticmethod
    def _validate_sha256(expected_sha256: str) -> str:
        value = str(expected_sha256).strip().lower()

        if not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("expected_sha256 must contain 64 hex characters.")

        return value

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _validate_onnx(path: Path) -> None:
        """Load the model with ONNX Runtime to validate its structure."""

        try:
            import onnxruntime as ort

        except ImportError as exc:
            raise ModelUpdateError(
                "ONNX Runtime is required to validate model updates."
            ) from exc

        try:
            session = ort.InferenceSession(
                str(path),
                providers=["CPUExecutionProvider"],
            )

            inputs = session.get_inputs()

            if len(inputs) != 1:
                raise ModelUpdateError(
                    "The model must have exactly one input."
                )

            input_shape = inputs[0].shape

            if len(input_shape) != 4:
                raise ModelUpdateError(
                    "The model must use a four-dimensional NCHW input."
                )

            channels = input_shape[1]

            if isinstance(channels, int) and channels != 3:
                raise ModelUpdateError(
                    "The model must have three input channels."
                )

            if not session.get_outputs():
                raise ModelUpdateError(
                    "The model does not expose any output."
                )

            del session

        except ModelUpdateError:
            raise

        except Exception as exc:
            raise ModelUpdateError(
                f"ONNX model validation failed: {exc}"
            ) from exc

    def _download(
        self,
        url: str,
        destination: Path,
        expected_sha256: str,
    ) -> tuple[str, int]:
        """Download to a temporary file and verify its checksum."""

        self._validate_url(url)

        opener = urllib.request.build_opener(
            _HTTPSRedirectHandler()
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RADA-Edge-ModelUpdater/1.0",
                "Accept": "application/octet-stream",
            },
            method="GET",
        )

        digest = hashlib.sha256()
        total_bytes = 0

        try:
            with opener.open(
                request,
                timeout=self.timeout,
            ) as response:
                status = getattr(response, "status", 200)

                if status != 200:
                    raise ModelUpdateError(
                        f"Model server returned HTTP {status}."
                    )

                content_length = response.headers.get("Content-Length")

                if content_length:
                    try:
                        announced_size = int(content_length)
                    except ValueError as exc:
                        raise ModelUpdateError(
                            "Invalid Content-Length header."
                        ) from exc

                    if announced_size < 0:
                        raise ModelUpdateError(
                            "Invalid Content-Length header."
                        )

                    if announced_size > self.max_download_bytes:
                        raise ModelUpdateError(
                            "Model exceeds the configured download limit."
                        )

                with destination.open("xb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)

                        if not chunk:
                            break

                        total_bytes += len(chunk)

                        if total_bytes > self.max_download_bytes:
                            raise ModelUpdateError(
                                "Model exceeds the configured download limit."
                            )

                        digest.update(chunk)
                        output.write(chunk)

                    output.flush()
                    os.fsync(output.fileno())

        except ModelUpdateError:
            raise

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            raise ModelUpdateError(
                f"Model download failed: {exc}"
            ) from exc

        actual_sha256 = digest.hexdigest()

        if total_bytes <= 0:
            raise ModelUpdateError("Downloaded model is empty.")

        if actual_sha256 != expected_sha256:
            raise ModelUpdateError(
                "SHA-256 verification failed. "
                f"Expected {expected_sha256}, received {actual_sha256}."
            )

        return actual_sha256, total_bytes

    def _write_manifest(
        self,
        *,
        version: str,
        sha256: str,
        size_bytes: int,
        updated_at: str,
    ) -> None:
        """Atomically write the installed model metadata."""

        manifest = {
            "version": version,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "updated_at": updated_at,
            "model_path": self.model_path.name,
        }

        self.manifest_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd, temporary_name = tempfile.mkstemp(
            prefix=".rada-manifest-",
            suffix=".tmp",
            dir=self.manifest_path.parent,
        )

        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(
                    manifest,
                    file,
                    indent=2,
                    sort_keys=True,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(
                temporary_path,
                self.manifest_path,
            )

        finally:
            temporary_path.unlink(missing_ok=True)

    def install(
        self,
        *,
        url: str,
        version: str,
        expected_sha256: str,
        reload_callback: Callable[[Path], Any] | None = None,
    ) -> ModelUpdateResult:
        """Install a verified model and optionally reload the detector.

        If reload_callback raises an exception, the old model is restored.
        """

        version = self._validate_version(version)
        expected_sha256 = self._validate_sha256(expected_sha256)
        self._validate_url(url)

        with self._lock:
            self.model_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.backup_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            fd, temporary_name = tempfile.mkstemp(
                prefix=".rada-model-",
                suffix=".onnx",
                dir=self.model_path.parent,
            )
            os.close(fd)

            temporary_path = Path(temporary_name)
            previous_model_exists = self.model_path.is_file()
            installed = False

            try:
                actual_sha256, size_bytes = self._download(
                    url,
                    temporary_path,
                    expected_sha256,
                )

                self._validate_onnx(temporary_path)

                if previous_model_exists:
                    # Keep the last working model before replacing it.
                    shutil.copy2(
                        self.model_path,
                        self.backup_path,
                    )

                os.replace(
                    temporary_path,
                    self.model_path,
                )
                installed = True

                try:
                    if reload_callback is not None:
                        reload_callback(self.model_path)

                except Exception as exc:
                    if previous_model_exists and self.backup_path.is_file():
                        os.replace(
                            self.backup_path,
                            self.model_path,
                        )
                    else:
                        self.model_path.unlink(missing_ok=True)

                    raise ModelUpdateError(
                        "New model was installed but detector reload "
                        f"failed; previous model restored: {exc}"
                    ) from exc

                updated_at = (
                    datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )

                try:
                    self._write_manifest(
                        version=version,
                        sha256=actual_sha256,
                        size_bytes=size_bytes,
                        updated_at=updated_at,
                    )
                except Exception:
                    # Do not report a successful update if metadata
                    # could not be persisted.
                    if previous_model_exists and self.backup_path.is_file():
                        os.replace(
                            self.backup_path,
                            self.model_path,
                        )
                    else:
                        self.model_path.unlink(missing_ok=True)

                    raise

                return ModelUpdateResult(
                    status="updated",
                    model_path=str(self.model_path),
                    version=version,
                    sha256=actual_sha256,
                    size_bytes=size_bytes,
                    updated_at=updated_at,
                    restart_required=reload_callback is None,
                    backup_path=(
                        str(self.backup_path)
                        if previous_model_exists
                        else None
                    ),
                )

            except ModelUpdateError:
                raise

            except Exception as exc:
                raise ModelUpdateError(
                    f"Model update failed: {exc}"
                ) from exc

            finally:
                temporary_path.unlink(missing_ok=True)

    def rollback(
        self,
        reload_callback: Callable[[Path], Any] | None = None,
    ) -> Path:
        """Restore the last backup model."""

        with self._lock:
            if not self.backup_path.is_file():
                raise ModelUpdateError(
                    "No backup model is available for rollback."
                )

            self._validate_onnx(self.backup_path)

            rollback_temp = self.model_path.with_name(
                f".{self.model_path.name}.rollback"
            )

            try:
                shutil.copy2(
                    self.backup_path,
                    rollback_temp,
                )

                self._validate_onnx(rollback_temp)

                os.replace(
                    rollback_temp,
                    self.model_path,
                )

                if reload_callback is not None:
                    try:
                        reload_callback(self.model_path)
                    except Exception as exc:
                        raise ModelUpdateError(
                            "Rollback file restored but detector reload "
                            f"failed: {exc}"
                        ) from exc

                return self.model_path

            finally:
                rollback_temp.unlink(missing_ok=True)

    def get_installed_version(self) -> dict[str, Any] | None:
        """Read the local model manifest."""

        if not self.manifest_path.is_file():
            return None

        try:
            with self.manifest_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                manifest = json.load(file)

            if not isinstance(manifest, dict):
                return None

            return manifest

        except (OSError, json.JSONDecodeError):
            return None


def create_model_updater(
    config: Mapping[str, Any],
) -> ModelUpdater:
    """Create a model updater from edge/config.yaml."""

    detector = config.get("detector", {})
    update = config.get("model_update", {})

    if not isinstance(detector, Mapping):
        raise ValueError("Invalid detector configuration.")

    if not isinstance(update, Mapping):
        raise ValueError("Invalid model_update configuration.")

    return ModelUpdater(
        model_path=detector.get(
            "model_path",
            "models/yolo.onnx",
        ),
        backup_path=update.get("backup_path"),
        manifest_path=update.get("manifest_path"),
        max_download_bytes=int(
            update.get("max_download_bytes", 2_000_000_000)
        ),
        timeout=float(
            update.get("timeout", 60.0)
        ),
    )
