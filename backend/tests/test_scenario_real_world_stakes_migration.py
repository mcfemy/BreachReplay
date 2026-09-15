"""
Round-trip test for migrations/versions/0051_scenario_real_world_stakes.py.

0051 adds scenarios.real_world_stakes and backfills the five flagship
scenarios by source_reference. Same isolation pattern as 0050: stamp prior
revision, run only 0051's upgrade()/downgrade().
"""
import importlib.util
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401
from seed import (
    COLONIAL_PIPELINE,
    LOG4SHELL,
    MGM_GRAND,
    NHS_WANNACRY,
    SOLARWINDS,
)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0051_scenario_real_world_stakes"
_PRIOR_REVISION = "0050_action_run_length_mode"


def _load_migration_module():
    path = os.path.join(
        _BACKEND_DIR, "migrations", "versions", "0051_scenario_real_world_stakes.py"
    )
    spec = importlib.util.spec_from_file_location("m0051_stakes", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_M0051 = _load_migration_module()
_STAKES_BY_SOURCE_REF: dict[str, str] = _M0051._STAKES_BY_SOURCE_REF


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0051_metadata() -> sa.MetaData:
    """Current ORM schema minus the column 0051 adds to scenarios."""
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name != "scenarios":
            table.to_metadata(baseline)
            continue
        cols = [c.copy() for c in table.columns if c.name != "real_world_stakes"]
        sa.Table(table.name, baseline, *cols, schema=table.schema)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'scenario_real_world_stakes_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0051_metadata().create_all(engine)
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
    conn.execute(
        text("""
            INSERT INTO scenarios (
                id, title, source_type, source_reference, difficulty,
                estimated_minutes, compression_ratio, status, is_synthetic,
                is_private, version, play_count, created_at, updated_at
            )
            VALUES (
                :id, :title, 'manual', :ref, 'practitioner',
                45, 8.0, 'approved', 0, 0, 1, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
        {
            "id": scenario_id,
            "title": f"Scenario {scenario_id}",
            "ref": source_reference,
        },
    )


def test_seed_and_migration_stakes_stay_in_sync():
    """Migration backfill and seed dicts must stay identical by construction."""
    seed_by_ref = {
        COLONIAL_PIPELINE["source_reference"]: COLONIAL_PIPELINE["real_world_stakes"],
        SOLARWINDS["source_reference"]: SOLARWINDS["real_world_stakes"],
        MGM_GRAND["source_reference"]: MGM_GRAND["real_world_stakes"],
        LOG4SHELL["source_reference"]: LOG4SHELL["real_world_stakes"],
        NHS_WANNACRY["source_reference"]: NHS_WANNACRY["real_world_stakes"],
    }
    assert seed_by_ref == _STAKES_BY_SOURCE_REF


def test_upgrade_adds_column_and_backfills_flagship_stakes(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        for i, ref in enumerate(_STAKES_BY_SOURCE_REF):
            _insert_scenario(conn, f"scenario-flagship-{i}", ref)
        _insert_scenario(conn, "scenario-unrelated-1", "UNRELATED-REF")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        assert "real_world_stakes" in columns

        for i, (ref, expected) in enumerate(_STAKES_BY_SOURCE_REF.items()):
            value = conn.execute(
                text(
                    "SELECT real_world_stakes FROM scenarios "
                    "WHERE id = :id"
                ),
                {"id": f"scenario-flagship-{i}"},
            ).scalar_one()
            assert value == expected, f"stakes mismatch for {ref}"

        unrelated = conn.execute(
            text(
                "SELECT real_world_stakes FROM scenarios "
                "WHERE id = 'scenario-unrelated-1'"
            )
        ).scalar_one()
        assert unrelated is None


def test_downgrade_drops_real_world_stakes_column(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-colonial", "CISA-AA21-131A")

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        assert "real_world_stakes" not in columns


def test_reupgrade_after_downgrade_restores_stakes(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-colonial", "CISA-AA21-131A")

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        assert "real_world_stakes" in columns
        value = conn.execute(
            text(
                "SELECT real_world_stakes FROM scenarios "
                "WHERE id = 'scenario-colonial'"
            )
        ).scalar_one()
        assert value == _STAKES_BY_SOURCE_REF["CISA-AA21-131A"]
