"""
Round-trip test for migrations/versions/0035_cmmc_evidence_layer_tenancy.py
(Phase 2.5, build-order item 1).

Same pattern as test_action_runs_migration.py: build the "as of 0034"
baseline schema directly from the current ORM models (excluding the 4 new
tables 0035 introduces), stamp Alembic to "0034_proportionate_response"
without running anything, then upgrade to "0035_..." in isolation — this
exercises exactly what 0035's own upgrade()/downgrade() do, not the rest
of the migration history.

`action_runs` stays in the baseline (unlike action_run's own migration
test, which excludes it) since 0035 only ADDS a column to that
already-existing table — it doesn't create it.
"""
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. the 4 new ones) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NEW_TABLES = {"consulting_orgs", "client_orgs", "memberships", "evidence_sessions"}
# Tables that don't exist yet as of migration 0035 (this test's subject)
# but DO exist in the CURRENT Base.metadata because a later migration
# added them — item 7's issued_evidence_packs (migration 0037) has a FK
# to evidence_sessions, which IS in _NEW_TABLES and gets excluded from
# the baseline below; without also excluding issued_evidence_packs here,
# to_metadata() would try to clone a FK pointing at a table that was
# never added to the baseline, raising NoReferencedTableError. This test
# never runs migration 0037 at all (it upgrades only as far as 0035), so
# issued_evidence_packs correctly has no business existing anywhere in
# this test's baseline OR post-upgrade schema.
_TABLES_NOT_YET_EXISTING_AT_0035 = _NEW_TABLES | {"issued_evidence_packs"}

_EXPECTED_MEMBERSHIP_COLUMNS = {
    "id", "user_id", "consulting_org_id", "client_org_id", "role", "joined_at",
}
# Columns on `users` added after migration 0035 — baseline must omit them
# so raw-SQL inserts in this test don't need tokens that didn't exist yet.
_USER_COLS_EXCLUDED_AT_0035 = frozenset({
    "seen_verb_coachmarks",  # 0040
    "beat_notifications_enabled",
    "email_unsubscribe_token",
    "has_acknowledged_racing_notice",  # 0043
})
_EXPECTED_ACTION_RUNS_COLUMNS_SUPERSET = {"evidence_session_id"}  # added on top of 0034's existing set


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'cmmc_tenancy_migration.db'}"
    engine = create_engine(sqlite_url)

    # Base.metadata reflects the CURRENT ActionRun model, which already
    # declares evidence_session_id (0035 added it directly to the model,
    # not just the migration) — a plain create_all would build action_runs
    # WITH that column already present, and 0035's own ADD COLUMN would
    # collide with it. Rather than create-then-DROP-COLUMN (tried first;
    # SQLite refuses to drop a column that carries a foreign key — the
    # same restriction the real migration's downgrade() has to work around
    # with batch mode), build the baseline schema from a filtered copy of
    # the metadata: every table cloned as-is via tometadata() except
    # action_runs, which is rebuilt column-by-column excluding
    # evidence_session_id — so it's never created in the first place.
    baseline_metadata = sa.MetaData()
    for name, table in Base.metadata.tables.items():
        if name in _TABLES_NOT_YET_EXISTING_AT_0035:
            continue
        if name == "action_runs":
            cols = [c.copy() for c in table.columns if c.name != "evidence_session_id"]
            sa.Table(name, baseline_metadata, *cols)
        elif name == "users":
            cols = [c.copy() for c in table.columns if c.name not in _USER_COLS_EXCLUDED_AT_0035]
            sa.Table(name, baseline_metadata, *cols)
        else:
            table.to_metadata(baseline_metadata)
    baseline_metadata.create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, "0034_proportionate_response")
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def test_upgrade_creates_all_four_new_tables_with_expected_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, "0035_cmmc_evidence_layer_tenancy")

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert _NEW_TABLES.issubset(tables)

    with engine.connect() as conn:
        membership_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(memberships)"))}
    assert membership_columns == _EXPECTED_MEMBERSHIP_COLUMNS

    with engine.connect() as conn:
        action_run_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert _EXPECTED_ACTION_RUNS_COLUMNS_SUPERSET.issubset(action_run_columns)


def test_membership_partial_unique_indexes_exist_after_upgrade(migration_engine):
    """Confirms the migration's raw DDL actually creates the two partial
    unique indexes (not just the ORM model) — this is what a real
    Postgres/SQLite deploy gets, independent of anything test-only about
    Base.metadata.create_all."""
    engine, cfg = migration_engine
    command.upgrade(cfg, "0035_cmmc_evidence_layer_tenancy")

    with engine.connect() as conn:
        index_names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert "uq_membership_user_consulting_org" in index_names
    assert "uq_membership_user_client_org" in index_names


def test_upgrade_then_check_constraint_rejects_role_org_mismatch_via_raw_sql(migration_engine):
    """Same intent as test_cmmc_isolation.py's ORM-level test, but against
    the migration's OWN raw CHECK constraint DDL directly — proves the
    constraint the migration actually ships, not just what the ORM model
    (a separate code path, used by Base.metadata.create_all in every other
    test) declares."""
    engine, cfg = migration_engine
    command.upgrade(cfg, "0035_cmmc_evidence_layer_tenancy")

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO consulting_orgs (id, name, branding, created_at) "
            "VALUES ('co-1', 'Test RPO', '{}', CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "INSERT INTO users (id, email, hashed_password, full_name, role, is_active, created_at, updated_at) "
            "VALUES ('u-1', 'raw-sql@example.com', 'x', 'x', 'analyst', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            # role says consultant_admin but client_org_id is set instead
            # of consulting_org_id — must violate ck_membership_role_matches_org.
            conn.execute(text(
                "INSERT INTO memberships (id, user_id, consulting_org_id, client_org_id, role, joined_at) "
                "VALUES ('m-1', 'u-1', NULL, 'does-not-even-need-to-exist', 'consultant_admin', CURRENT_TIMESTAMP)"
            ))


def test_downgrade_drops_all_four_new_tables_and_action_runs_column_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, "0035_cmmc_evidence_layer_tenancy")

    command.downgrade(cfg, "-1")
    with engine.connect() as conn:
        tables_after_downgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert not (_NEW_TABLES & tables_after_downgrade)

    with engine.connect() as conn:
        action_run_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert "evidence_session_id" not in action_run_columns

    # Re-upgrading after a downgrade must work too — proves downgrade left
    # no partial state behind (a stray index/constraint it failed to drop).
    command.upgrade(cfg, "0035_cmmc_evidence_layer_tenancy")
    with engine.connect() as conn:
        tables_after_reupgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert _NEW_TABLES.issubset(tables_after_reupgrade)
