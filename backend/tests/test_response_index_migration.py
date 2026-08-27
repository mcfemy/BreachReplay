"""
Round-trip test for migrations/versions/0046_response_index.py.
"""
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0046_response_index"
_PRIOR_REVISION = "0045_ghost_race_beat_email_sent"

_NEW_COLUMN = "response_index"


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0046_metadata() -> sa.MetaData:
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name != "users":
            table.to_metadata(baseline)
            continue
        cols = [c.copy() for c in table.columns if c.name != _NEW_COLUMN]
        sa.Table(table.name, baseline, *cols, schema=table.schema)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'response_index_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0046_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_legacy_user(conn, user_id: str, email: str) -> None:
    conn.execute(
        text("""
            INSERT INTO users (
                id, email, hashed_password, full_name, role, is_active,
                arena_rating, beat_notifications_enabled, email_unsubscribe_token,
                has_acknowledged_racing_notice, created_at, updated_at
            )
            VALUES (
                :id, :email, 'x', 'Legacy User', 'analyst', 1,
                1200, 1, :token, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
        {"id": user_id, "email": email, "token": f"tok-{user_id}"},
    )


def test_upgrade_adds_response_index_default_1200(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_legacy_user(conn, "u-1", "one@example.com")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert _NEW_COLUMN in columns
        value = conn.execute(
            text("SELECT response_index FROM users WHERE id = 'u-1'")
        ).scalar_one()
        assert value == 1200


def test_downgrade_drops_response_index(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert _NEW_COLUMN not in columns


def test_reupgrade_after_downgrade_restores_response_index(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_legacy_user(conn, "u-re", "reupgrade@example.com")

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert _NEW_COLUMN in columns
        value = conn.execute(
            text("SELECT response_index FROM users WHERE id = 'u-re'")
        ).scalar_one()
        assert value == 1200
