"""
Round-trip test for migrations/versions/0038_scenario_notification_matrix.py
(Phase 3 — Targeted Escalation & Notification Proportionality, review
finding on PR #25: 0038 was "verified standalone" only via a self-report,
never actually round-tripped in CI).

Same "stamp-then-step" approach as test_scenario_is_synthetic_migration.py
(0031's own test) — adapted for a column that backfills real per-scenario
JSONB content keyed by `source_reference` (mirroring 0034's
collateral_weights backfill), rather than a bulk boolean remediation.
`_pre_0038_metadata` mirrors that file's `_pre_0031_metadata` exactly: copy
every current ORM table over via `to_metadata`, except `scenarios`, whose
columns are copied individually with `notification_matrix` left out —
`Base.metadata` already has that column since it's built from the current
model.
"""
import os
import warnings

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. Scenario) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0038_scenario_notification_matrix"
_PRIOR_REVISION = "0037_cmmc_issued_evidence_packs"

# The exact source_reference migration 0038's upgrade() backfills — mirrored
# here (not imported), same discipline test_scenario_is_synthetic_migration.py
# already applies: a migration's own logic should be exercised byte-for-byte
# as authored, not via a shared import from application code.
_SOLARWINDS_SOURCE_REF = "CISA-AA20-352A"


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0038_metadata() -> MetaData:
    """Every current ORM table, except `scenarios` loses its
    `notification_matrix` column — reproducing the schema exactly as it
    existed at 0037, since `Base.metadata` (built from the current model)
    already has the column 0038 introduces."""
    baseline = MetaData()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # Column.copy() (SQLAlchemy 1.4+)
        for table in Base.metadata.sorted_tables:
            if table.name == "scenarios":
                cols = [c.copy() for c in table.columns if c.name != "notification_matrix"]
                Table(table.name, baseline, *cols)
            else:
                table.to_metadata(baseline)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'scenario_notification_matrix_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0038_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_scenario(conn, scenario_id: str, source_reference: str) -> None:
    # Every NOT NULL column whose default is Python-side only (set by the
    # ORM, not the DB) needs an explicit value here — this raw INSERT
    # bypasses the ORM entirely, same reason test_scenario_is_synthetic_
    # migration.py's own insert helper spells out every column rather than
    # relying on model defaults.
    conn.execute(
        text("""
            INSERT INTO scenarios
                (id, title, source_type, source_reference, difficulty, estimated_minutes,
                 compression_ratio, status, is_synthetic, is_private, version, play_count,
                 created_at, updated_at)
            VALUES
                (:id, 'Test Scenario', 'manual', :ref, 'practitioner', 45, 8.0,
                 'approved', 0, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {"id": scenario_id, "ref": source_reference},
    )


def test_upgrade_adds_notification_matrix_column_defaulting_empty_list(migration_engine):
    """The real gap the reviewer flagged: 0038's upgrade() must actually
    run (not just exist) against a schema that doesn't have the column
    yet, and existing rows must backfill to an empty list via the
    server_default — not NULL, which verb_engine's `_field(scenario,
    "notification_matrix") or []` fallback tolerates, but a raw NULL
    would fail json.loads() in any code path that isn't that defensive."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-unrelated-1", "SOME-OTHER-SOURCE-REF")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        assert "notification_matrix" in columns

        value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-unrelated-1'")
        ).scalar()
    assert value in ("[]", []), f"expected an empty list, got {value!r}"


def test_upgrade_backfills_solarwinds_matrix_and_leaves_other_scenarios_empty(migration_engine):
    """The real backfill half of 0038: the row matching SolarWinds'
    source_reference gets the full authored matrix; an unrelated
    scenario's row must be untouched (empty list, not accidentally
    sharing the same backfilled content)."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-solarwinds", _SOLARWINDS_SOURCE_REF)
        _insert_scenario(conn, "scenario-unrelated-1", "SOME-OTHER-SOURCE-REF")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        solarwinds_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-solarwinds'")
        ).scalar()
        other_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-unrelated-1'")
        ).scalar()

    import json
    solarwinds_matrix = json.loads(solarwinds_value) if isinstance(solarwinds_value, str) else solarwinds_value
    assert len(solarwinds_matrix) == 6  # CISA, DC3, legal, insurer, prime, state_ag
    party_ids = {p["id"] for p in solarwinds_matrix}
    assert party_ids == {"cisa", "dc3", "legal", "insurer", "prime", "state_ag"}
    warranted_by_id = {p["id"]: p["warranted"] for p in solarwinds_matrix}
    assert warranted_by_id["state_ag"] is False
    assert warranted_by_id["cisa"] is True

    other_matrix = json.loads(other_value) if isinstance(other_value, str) else other_value
    assert other_matrix == []


def test_downgrade_drops_notification_matrix_column(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-solarwinds", _SOLARWINDS_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        columns_after_upgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
    assert "notification_matrix" in columns_after_upgrade

    command.downgrade(cfg, _PRIOR_REVISION)
    with engine.connect() as conn:
        columns_after_downgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
    assert "notification_matrix" not in columns_after_downgrade


def test_reupgrade_after_downgrade_restores_the_column_and_backfill_cleanly(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-solarwinds", _SOLARWINDS_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-solarwinds'")
        ).scalar()
    assert "notification_matrix" in columns

    import json
    matrix = json.loads(value) if isinstance(value, str) else value
    assert len(matrix) == 6
