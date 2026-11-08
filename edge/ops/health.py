"""edge/ops/health.py — TODO: implement (see docs/architecture.md)."""
"""Health monitoring for the RADA AI edge runtime."""

from __future__ import annotations

import os
import shutil
import time
import urllib.error
import urllib.request

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_cpu_times() -> tuple[int, int] | None:
    """Return Linux CPU total and idle counters."""

    try:
        with open("/proc/stat", encoding="utf-8") as file:
            line = file.readline()

        values = [int(value) for value in line.split()[1:]]

        if len(values) < 4:
            return None

        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)

        return total, idle

    except (OSError, ValueError, IndexError):
        return None


def _cpu_usage_percent(interval: float = 0.1) -> float | None:
    """Estimate CPU utilization from Linux CPU counters."""

    first = _read_cpu_times()

    if first is None:
        return None

    time.sleep(max(0.0, interval))

    second = _read_cpu_times()

    if second is None:
        return None

    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]

    if total_delta <= 0:
        return None

    usage = 100.0 * (total_delta - idle_delta) / total_delta

    return round(max(0.0, min(100.0, usage)), 2)


def _memory_usage() -> dict[str, int | float] | None:
    """Read Linux memory usage from /proc/meminfo."""

    try:
        values: dict[str, int] = {}

        with open("/proc/meminfo", encoding="utf-8") as file:
            for line in file:
                key, raw_value = line.split(":", 1)
                values[key] = int(raw_value.strip().split()[0]) * 1024

        total = values.get("MemTotal")
        available = values.get("MemAvailable")

        if not total or available is None:
            return None

        used = total - available

        return {
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": available,
            "usage_percent": round(used / total * 100.0, 2),
        }

    except (OSError, ValueError, IndexError):
        return None


def _process_memory_bytes() -> int | None:
    """Read current process resident memory from procfs."""

    try:
        with open("/proc/self/statm", encoding="utf-8") as file:
            resident_pages = int(file.read().split()[1])

        page_size = os.sysconf("SC_PAGE_SIZE")

        return resident_pages * page_size

    except (OSError, ValueError, IndexError, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """One health check result."""

    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Complete edge health report."""

    status: str
    timestamp: str
    uptime_seconds: float
    checks: tuple[HealthCheck, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "uptime_seconds": self.uptime_seconds,
            "checks": [
                check.to_dict()
                for check in self.checks
            ],
            "metrics": self.metrics,
        }


class HealthReporter:
    """Collect health information for an edge device."""

    def __init__(
        self,
        *,
        backend_url: str | None = None,
        storage_path: str | Path = ".",
        model_path: str | Path | None = None,
        cpu_warning_percent: float = 90.0,
        memory_warning_percent: float = 90.0,
        disk_warning_percent: float = 90.0,
        backend_timeout: float = 2.0,
    ) -> None:
        for name, value in (
            ("cpu_warning_percent", cpu_warning_percent),
            ("memory_warning_percent", memory_warning_percent),
            ("disk_warning_percent", disk_warning_percent),
        ):
            if not 0 < value <= 100:
                raise ValueError(f"{name} must be between 0 and 100.")

        if backend_timeout <= 0:
            raise ValueError("backend_timeout must be positive.")

        self.backend_url = backend_url.rstrip("/") if backend_url else None
        self.storage_path = Path(storage_path)
        self.model_path = Path(model_path) if model_path else None

        self.cpu_warning_percent = cpu_warning_percent
        self.memory_warning_percent = memory_warning_percent
        self.disk_warning_percent = disk_warning_percent
        self.backend_timeout = backend_timeout

        self.started_at = time.monotonic()

    def _check_model(self) -> HealthCheck:
        if self.model_path is None:
            return HealthCheck(
                name="model",
                status="unknown",
                message="No model path configured.",
            )

        if not self.model_path.is_file():
            return HealthCheck(
                name="model",
                status="unhealthy",
                message="Configured model file does not exist.",
                details={"path": str(self.model_path)},
            )

        size = self.model_path.stat().st_size

        if size <= 0:
            return HealthCheck(
                name="model",
                status="unhealthy",
                message="Model file is empty.",
                details={"path": str(self.model_path)},
            )

        return HealthCheck(
            name="model",
            status="healthy",
            message="Model file is present.",
            details={
                "path": str(self.model_path),
                "size_bytes": size,
            },
        )

    def _check_storage(self) -> tuple[HealthCheck, dict[str, Any]]:
        try:
            usage = shutil.disk_usage(self.storage_path)

            percent = (
                usage.used / usage.total * 100.0
                if usage.total
                else 0.0
            )

            details = {
                "path": str(self.storage_path),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "usage_percent": round(percent, 2),
            }

            if percent >= self.disk_warning_percent:
                status = "degraded"
                message = "Disk usage is above the warning threshold."
            else:
                status = "healthy"
                message = "Disk storage is available."

            return (
                HealthCheck(
                    name="storage",
                    status=status,
                    message=message,
                    details=details,
                ),
                details,
            )

        except OSError as exc:
            return (
                HealthCheck(
                    name="storage",
                    status="unhealthy",
                    message=f"Storage check failed: {exc}",
                ),
                {},
            )

    def _check_backend(self) -> HealthCheck:
        if not self.backend_url:
            return HealthCheck(
                name="backend",
                status="unknown",
                message="Backend URL is not configured.",
            )

        url = f"{self.backend_url}/health"

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "RADA-Edge-Health/1.0"},
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.backend_timeout,
            ) as response:
                status_code = response.status

            if 200 <= status_code < 300:
                return HealthCheck(
                    name="backend",
                    status="healthy",
                    message="Backend health endpoint responded.",
                    details={
                        "status_code": status_code,
                        "url": url,
                    },
                )

            return HealthCheck(
                name="backend",
                status="unhealthy",
                message="Backend returned an unsuccessful status.",
                details={"status_code": status_code},
            )

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            return HealthCheck(
                name="backend",
                status="unhealthy",
                message=f"Backend is unreachable: {exc}",
                details={"url": url},
            )

    def collect(
        self,
        *,
        camera_ok: bool | None = None,
        detector_ok: bool | None = None,
        extra_checks: Mapping[str, bool | None] | None = None,
    ) -> HealthReport:
        """Collect health checks and runtime metrics.

        None means unknown, not healthy.
        """

        checks: list[HealthCheck] = []

        cpu = _cpu_usage_percent()

        if cpu is None:
            checks.append(
                HealthCheck(
                    name="cpu",
                    status="unknown",
                    message="CPU metrics are unavailable.",
                )
            )
        else:
            checks.append(
                HealthCheck(
                    name="cpu",
                    status=(
                        "degraded"
                        if cpu >= self.cpu_warning_percent
                        else "healthy"
                    ),
                    message="CPU utilization measured.",
                    details={"usage_percent": cpu},
                )
            )

        memory = _memory_usage()

        if memory is None:
            checks.append(
                HealthCheck(
                    name="memory",
                    status="unknown",
                    message="Memory metrics are unavailable.",
                )
            )
        else:
            memory_percent = float(memory["usage_percent"])

            checks.append(
                HealthCheck(
                    name="memory",
                    status=(
                        "degraded"
                        if memory_percent >= self.memory_warning_percent
                        else "healthy"
                    ),
                    message="System memory measured.",
                    details=memory,
                )
            )

        process_memory = _process_memory_bytes()

        checks.append(
            HealthCheck(
                name="process",
                status="healthy",
                message="Edge process is running.",
                details={
                    "pid": os.getpid(),
                    "resident_memory_bytes": process_memory,
                },
            )
        )

        storage_check, storage_metrics = self._check_storage()
        checks.append(storage_check)

        checks.append(self._check_model())
        checks.append(self._check_backend())

        checks.append(
            HealthCheck(
                name="camera",
                status=(
                    "unknown"
                    if camera_ok is None
                    else "healthy" if camera_ok else "unhealthy"
                ),
                message=(
                    "Camera state was not supplied."
                    if camera_ok is None
                    else "Camera stream is available."
                    if camera_ok
                    else "Camera stream is unavailable."
                ),
            )
        )

        checks.append(
            HealthCheck(
                name="detector",
                status=(
                    "unknown"
                    if detector_ok is None
                    else "healthy" if detector_ok else "unhealthy"
                ),
                message=(
                    "Detector state was not supplied."
                    if detector_ok is None
                    else "Detector is operational."
                    if detector_ok
                    else "Detector is not operational."
                ),
            )
        )

        for name, result in (extra_checks or {}).items():
            if not name or name in {
                "cpu", "memory", "process", "storage",
                "model", "backend", "camera", "detector",
            }:
                raise ValueError(f"Invalid or reserved health check name: {name}")

            checks.append(
                HealthCheck(
                    name=name,
                    status=(
                        "unknown"
                        if result is None
                        else "healthy" if result else "unhealthy"
                    ),
                    message=f"Custom check: {name}.",
                )
            )

        statuses = {check.status for check in checks}

        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        elif "unknown" in statuses:
            overall_status = "unknown"
        else:
            overall_status = "healthy"

        return HealthReport(
            status=overall_status,
            timestamp=_utc_now(),
            uptime_seconds=round(
                time.monotonic() - self.started_at,
                2,
            ),
            checks=tuple(checks),
            metrics={
                "cpu_usage_percent": cpu,
                "system_memory": memory,
                "process_memory_bytes": process_memory,
                "storage": storage_metrics,
            },
        )


def create_health_reporter(
    config: Mapping[str, Any],
) -> HealthReporter:
    """Create a health reporter from edge/config.yaml."""

    transport = config.get("transport", {})
    detector = config.get("detector", {})
    health = config.get("health", {})

    if not isinstance(transport, Mapping):
        raise ValueError("Invalid transport configuration.")

    if not isinstance(detector, Mapping):
        raise ValueError("Invalid detector configuration.")

    if not isinstance(health, Mapping):
        raise ValueError("Invalid health configuration.")

    backend_url = transport.get("backend_url")
    model_path = detector.get("model_path")

    return HealthReporter(
        backend_url=str(backend_url) if backend_url else None,
        storage_path=health.get("storage_path", "."),
        model_path=model_path,
        cpu_warning_percent=float(
            health.get("cpu_warning_percent", 90.0)
        ),
        memory_warning_percent=float(
            health.get("memory_warning_percent", 90.0)
        ),
        disk_warning_percent=float(
            health.get("disk_warning_percent", 90.0)
        ),
        backend_timeout=float(
            health.get("backend_timeout", 2.0)
        ),
    )
