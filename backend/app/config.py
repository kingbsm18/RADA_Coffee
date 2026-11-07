from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://rada:change_me@db:5432/rada"
    secret_key: str = "change_me"
    storage_backend: str = "local"
    snapshot_dir: str = "/data/snapshots"
    timezone: str = "Africa/Casablanca"
    currency: str = "MAD"


settings = Settings()
