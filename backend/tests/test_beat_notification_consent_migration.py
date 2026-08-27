"""
Round-trip test for migrations/versions/0043_beat_notification_consent.py.
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
_TARGET_REVISION = "0043_beat_notification_consent"
_PRIOR_REVISION = "0042_log4shell_notification_matrix"

_NEW_COLUMNS = {
    "beat_notifications_enabled",
    "email_unsubscribe_token",
    "has_acknowledged_racing_notice",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0043_metadata() -> sa.MetaData:
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name != "users":
            table.to_metadata(baseline)
            continue
        # users table without 0043 columns
        cols = [
            c.copy() for c in table.columns
            if c.name not in _NEW_COLUMNS
        ]
        sa.Table(table.name, baseline, *cols, schema=table.schema)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'beat_notification_consent_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0043_metadata().create_all(engine)
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
                created_at, updated_at
            )
            VALUES (
                :id, :email, 'x', 'Legacy User', 'analyst', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
        {"id": user_id, "email": email},
    )


def test_upgrade_adds_columns_with_defaults_and_unique_tokens(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_legacy_user(conn, "u-1", "one@example.com")
        _insert_legacy_user(conn, "u-2", "two@example.com")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert _NEW_COLUMNS.issubset(columns)

        rows = conn.execute(
            text("""
                SELECT beat_notifications_enabled, email_unsubscribe_token,
                       has_acknowledged_racing_notice
                FROM users ORDER BY email
            """)
        ).fetchall()
        assert len(rows) == 2
        tokens = [r[1] for r in rows]
        assert all(t and len(t) >= 16 for t in tokens)
        assert len(set(tokens)) == 2
        assert all(r[0] == 1 for r in rows)  # beat_notifications_enabled true
        assert all(r[2] == 0 for r in rows)  # notice not yet acknowledged


def test_downgrade_drops_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert _NEW_COLUMNS.isdisjoint(columns)
