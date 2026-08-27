"""
Round-trip test for migrations/versions/0045_ghost_race_beat_email_sent.py.
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
_TARGET_REVISION = "0045_ghost_race_beat_email_sent"
_PRIOR_REVISION = "0044_ghost_race_beats"

_NEW_COLUMNS = {"email_sent_at", "email_delivered_at"}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0045_metadata() -> sa.MetaData:
    """ORM schema as of 0044 — ghost_race_beats without email tracking columns."""
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name == "ghost_race_beats":
            cols = [c.copy() for c in table.columns if c.name not in _NEW_COLUMNS]
            sa.Table(table.name, baseline, *cols, schema=table.schema)
            continue
        table.to_metadata(baseline)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'ghost_race_beat_email_sent_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0045_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def test_upgrade_adds_email_tracking_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(ghost_race_beats)"))}
        assert _NEW_COLUMNS.issubset(columns)


def test_downgrade_drops_email_tracking_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(ghost_race_beats)"))}
        assert _NEW_COLUMNS.isdisjoint(columns)


def test_reupgrade_after_downgrade_restores_email_tracking_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(ghost_race_beats)"))}
        assert _NEW_COLUMNS.issubset(columns)
