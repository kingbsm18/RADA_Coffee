"""Alembic must produce exactly the schema the models describe (PostgreSQL only)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

URL = os.environ.get("TEST_DATABASE_URL", "")
BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs PostgreSQL (set TEST_DATABASE_URL)")
def test_migrations_upgrade_match_models_and_downgrade_cleanly(engine, monkeypatch) -> None:
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app.database import Base

    Base.metadata.drop_all(engine)
    with engine.begin() as connection:  # leftovers of an aborted run must not matter
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setattr("app.config.settings.database_url", URL)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))

    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            drift = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
        assert drift == [], f"models and migrations differ: {drift}"

        command.downgrade(config, "base")
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()
        command.upgrade(config, "head")  # and it can be applied again
    finally:
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
