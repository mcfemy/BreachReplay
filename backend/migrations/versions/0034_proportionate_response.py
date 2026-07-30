"""Proportionate Response — outcome grading + collateral cost

Revision ID: 0034_proportionate_response
Revises: 0033_user_console_intro
Create Date: 2026-07-30 00:00:00.000000

Three things, in one migration because they're all part of the same
content/behavior change (see the "Proportionate Response" spec):

1. `scenarios.collateral_weights` (new JSONB column) — authored per-hostname
   collateral severity for the 4 flagship scenarios with stable, real
   hostnames (Colonial Pipeline, SolarWinds, Log4Shell, NHS WannaCry — see
   backend/seed.py's per-scenario dicts for the citations behind each
   number). MGM Resorts is left `{}`: all 10 of its hosts share one
   undifferentiated naming pattern (`BACKUP-VEEAM-{NN}`), so there is no
   hostname-level signal to author weights against without fabricating
   distinctions the content doesn't support — see docs/BACKLOG.md.

2. `scenarios.debrief_skeleton` — dropped. Zero references anywhere in
   service logic (confirmed by a repo-wide search); the new debrief
   narrative is computed dynamically from outcome + collateral breakdown,
   not stored per-scenario. This is the explicit resolution the spec asks
   for, not a third turn of leaving it ambiguous.

3. `action_runs.outcome` — converted from a native Postgres ENUM
   ("win"/"loss"/"partial") to `VARCHAR` + `CHECK` with 5 new values
   ("contained"/"contained_at_cost"/"overreacted"/"breached_spread_limited"/
   "breached"), then existing rows are backfilled (win->contained,
   partial->breached_spread_limited, loss->breached — best-effort remapping
   of historical rows; their score/penalties were computed under the old
   3-state rules and won't retroactively reflect collateral). Deliberately
   NOT a native-enum ADD VALUE: Postgres refuses to use a just-added enum
   value inside the same transaction that added it, and native enums can
   never cleanly drop old values either — both problems a plain CHECK
   constraint sidesteps for good.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0034_proportionate_response"
down_revision: Union[str, None] = "0033_user_console_intro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference (the same key seed.py's own seed()
# uses to identify a scenario), not title — precise and stable regardless
# of any future title copy-edit. See docs/precious-snuggling-micali plan
# (Part B) / backend/seed.py for the full per-host citations; kept in sync
# with seed.py's SCENARIOS dicts by hand since seed.py's own seed() only
# inserts NEW rows and never updates existing ones (see its skip-if-exists
# guard) — this migration is what actually lands the values on the 4
# scenarios already seeded in every real environment.
_COLLATERAL_WEIGHTS_BY_SOURCE_REF = {
    "CISA-AA21-131A": {  # Colonial Pipeline
        "CORP-DC-01": 80,
        "vpn-gw-01.colpipe.internal": 80,
        "OT-HISTORIAN-01": 80,
        "FIN-SVR-04": 60,
        "patch-mgmt-01": 40,
        "CORP-WKS-22": 25,
    },
    "CISA-AA20-352A": {  # SolarWinds
        "adfs-01.corp.internal": 80,
        "orion-mgmt-01": 80,
        "orion-mgmt-01.corp.internal": 80,
        "eu-west-1": 25,
    },
    "CVE-2021-44228": {  # Log4Shell
        "vcenter-01.prod.internal": 100,
        "api-gateway.prod.internal": 80,
        "es-prod-01": 60,
        "app-svr-03": 40,
        "app-svr-12": 40,
        "app-svr-14": 40,
        "app-svr-19": 40,
        "app-svr-22": 40,
    },
    "NHS-WannaCry-NCSC-2017": {  # NHS WannaCry
        "NHS-PACS-01": 100,
        "NHS-IMAGING-CTRL-02": 100,
        "WKS-ONCO-04": 80,
        "NHS-DOMAIN-CTRL-01": 80,
        "NHS-PTDB-01": 60,
        # Temporary — see docs/BACKLOG.md's "NHS WannaCry: legacy/unpatched
        # hosts are decoys, but that's backwards". These two hostnames are
        # the real WannaCry root-cause vulnerability class but currently
        # sit in the compiled decoy pool, not the attack path. Weighting
        # them at the tier their real-world significance would otherwise
        # earn (60+) would penalize a player who reasons correctly from the
        # actual incident — a knowledge penalty, live the moment this
        # ships. Low value stays until that placement bug is fixed;
        # cross-reference that BACKLOG item before ever raising these.
        "NHS-LEGACY-XP-03": 20,
        "NHS-SERVER-LEGACY-08": 20,
        "NHS-DESKTOP-014": 25,
        "WKS-ORTHO-11": 25,
        "WKS-ORTHO-12": 25,
    },
}

_OUTCOME_BACKFILL = {
    "win": "contained",
    "partial": "breached_spread_limited",
    "loss": "breached",
}


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1 & 2: scenarios.collateral_weights / drop debrief_skeleton ─────────
    op.add_column(
        "scenarios",
        sa.Column(
            "collateral_weights",
            JSONB().with_variant(sa.JSON, "sqlite"),
            nullable=False,
            server_default="{}",
        ),
    )
    op.drop_column("scenarios", "debrief_skeleton")

    # bind.execute(...) (a real Connection), not op.execute(...) — op.execute
    # only takes a SQL string/construct, it has no params argument, so a
    # bound sa.text(...) passed through it would silently never get its
    # bindparams filled in. bind.execute is the correct way to run a
    # parameterized statement from inside a migration.
    weights_col_type = JSONB if bind.dialect.name == "postgresql" else sa.JSON
    weights_stmt = sa.text(
        "UPDATE scenarios SET collateral_weights = :weights WHERE source_reference = :ref"
    ).bindparams(sa.bindparam("weights", type_=weights_col_type), sa.bindparam("ref", type_=sa.String))
    for source_ref, weights in _COLLATERAL_WEIGHTS_BY_SOURCE_REF.items():
        bind.execute(weights_stmt, {"weights": weights, "ref": source_ref})

    # ── 3: action_runs.outcome — native enum -> VARCHAR + CHECK ─────────────
    outcome_backfill_stmt = sa.text("UPDATE action_runs SET outcome = :new WHERE outcome = :old")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE action_runs ALTER COLUMN outcome TYPE VARCHAR USING outcome::text")
        for old, new in _OUTCOME_BACKFILL.items():
            bind.execute(outcome_backfill_stmt, {"new": new, "old": old})
        op.create_check_constraint(
            "ck_action_runs_outcome",
            "action_runs",
            "outcome IN ('contained','contained_at_cost','overreacted','breached_spread_limited','breached')",
        )
        op.execute("DROP TYPE action_run_outcome")
    else:
        # SQLite path: outcome was never a real native enum here (see
        # 0029's own docstring on postgresql.ENUM's generic-column
        # fallback), so there is no type to convert — only the value
        # backfill applies, for symmetry with the Postgres path above.
        for old, new in _OUTCOME_BACKFILL.items():
            bind.execute(outcome_backfill_stmt, {"new": new, "old": old})


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_action_runs_outcome", "action_runs", type_="check")
        from sqlalchemy.dialects import postgresql as pg
        action_run_outcome = pg.ENUM("win", "loss", "partial", name="action_run_outcome", create_type=False)
        action_run_outcome.create(bind, checkfirst=True)
        _REVERSE_BACKFILL = {v: k for k, v in _OUTCOME_BACKFILL.items()}
        reverse_stmt = sa.text("UPDATE action_runs SET outcome = :old WHERE outcome = :new")
        for new, old in _REVERSE_BACKFILL.items():
            bind.execute(reverse_stmt, {"old": old, "new": new})
        # Any run created under the 2 states that had no old-world
        # equivalent (contained_at_cost, overreacted) can't be losslessly
        # reversed — best-effort downgrade only, matching the upgrade's own
        # documented best-effort backfill.
        op.execute("UPDATE action_runs SET outcome = 'partial' WHERE outcome = 'contained_at_cost'")
        op.execute("UPDATE action_runs SET outcome = 'loss' WHERE outcome = 'overreacted'")
        op.execute("ALTER TABLE action_runs ALTER COLUMN outcome TYPE action_run_outcome USING outcome::action_run_outcome")

    op.add_column("scenarios", sa.Column("debrief_skeleton", JSONB().with_variant(sa.JSON, "sqlite"), nullable=True))
    op.drop_column("scenarios", "collateral_weights")
