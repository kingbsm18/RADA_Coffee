"""Runtime settings, read from environment variables (never from Git)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT = "change_me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # dev | local | hybrid | cloud. Anything but "dev" enforces strict secrets.
    environment: str = "dev"
    database_url: str = "postgresql+psycopg://rada:change_me@db:5432/rada"

    # Signs dashboard access tokens (HS256). Must be long and random outside dev.
    secret_key: str = INSECURE_DEFAULT
    access_token_minutes: int = 60
    password_hash_iterations: int = 600_000
    login_max_failures: int = 5
    login_window_seconds: int = 300

    # First admin, created at startup only when no user exists yet.
    admin_username: str | None = None
    admin_password: str | None = None
    admin_org_name: str = "RADA"

    cors_origins: str = ""  # comma-separated list of allowed dashboard origins

    storage_backend: str = "local"  # local | s3
    snapshot_dir: str = "/data/snapshots"
    snapshot_max_bytes: int = 2_000_000
    snapshot_retention_days: int = 30
    s3_bucket: str | None = None
    s3_prefix: str = "snapshots"

    pos_import_max_bytes: int = 5_000_000
    pos_import_max_rows: int = 50_000
    max_future_skew_seconds: int = 300  # reject events dated further in the future

    timezone: str = "Africa/Casablanca"
    currency: str = "MAD"
    feature_flags: str = ""  # comma-separated names

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_runtime_safe(self) -> None:
        """Refuse to start with default or weak secrets outside dev."""
        if self.environment == "dev":
            return
        if self.secret_key == INSECURE_DEFAULT or len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be a random value of 32+ characters")
        if self.admin_password is not None and len(self.admin_password) < 12:
            raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters")
        if "change_me" in self.database_url:
            raise RuntimeError("DATABASE_URL still uses the example password")


settings = Settings()


def assert_tz_database_current() -> None:
    """Morocco returned to UTC+0 on 2026-09-20. An outdated tz database would shift every
    local-time conversion by one hour and break the 5-30 minute matching windows."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    offset = datetime(2026, 11, 5, 12, 0, tzinfo=ZoneInfo("Africa/Casablanca")).utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise RuntimeError(
            "Outdated timezone database: Africa/Casablanca must be UTC+0 on 2026-11-05 "
            "(update the 'tzdata' package / base image)"
        )
