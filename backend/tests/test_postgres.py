"""Migration test against a real PostgreSQL server (set TEST_POSTGRES_URL to enable)."""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from core.config import BACKEND_DIR

pytestmark = pytest.mark.postgres


def test_alembic_upgrade_and_downgrade_roundtrip():
    url = os.environ["TEST_POSTGRES_URL"]
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["explicit_url"] = True
    cfg.attributes["skip_logging"] = True
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert {
        "repositories",
        "investigations",
        "events",
        "hypotheses",
        "experiments",
        "patches",
        "model_calls",
        "app_settings",
        "alembic_version",
    } <= tables
    columns = {c["name"]: c for c in inspect(engine).get_columns("investigations")}
    assert str(columns["usage"]["type"]) == "JSONB"
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    engine.dispose()
