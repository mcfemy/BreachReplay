"""Phase 5 — Scenario library case-file stakes (real_world_stakes).

Revision ID: 0051_scenario_real_world_stakes
Revises: 0050_action_run_length_mode
Create Date: 2026-09-08 00:00:00.000000

Adds a short, punchy `real_world_stakes` line per scenario for the library
card re-frame (BREACHREPLAY_GAME_OVERHAUL_SPEC.md §7). Values below are
independently verified public facts — not invented flavor text. Citations
kept in this docstring for auditability:

- Colonial (CISA-AA21-131A): CEO Joseph Blount publicly confirmed $4.4M
  ransom (WSJ / AP, May–Jun 2021); Colonial's own claim that the pipeline
  supplies ~45% of East Coast fuel (widely reported with that attribution).
- SolarWinds (CISA-AA20-352A): SolarWinds SEC disclosure — ~18,000 customers
  downloaded the trojanized Orion updates containing SUNBURST.
- MGM (MGM-2023-SEC-8K): MGM Form 8-K (Oct 2023) — ~$100M negative impact
  to Adjusted Property EBITDAR from the September cybersecurity issue.
- Log4Shell (CVE-2021-44228): Contrast Security / industry research commonly
  cites Log4j in ~64% of Java applications; vulnerability is critical RCE.
- NHS WannaCry (NHS-WannaCry-NCSC-2017): NAO / NHS England lessons learned —
  ~1/3 of trusts in England affected (80/236); thousands of appointments
  cancelled (NHS England identified 6,912; estimated >19,000 total).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_scenario_real_world_stakes"
down_revision: Union[str, None] = "0050_action_run_length_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matched by scenarios.source_reference — same convention as 0038/0042/0047–0049.
_STAKES_BY_SOURCE_REF: dict[str, str] = {
    "CISA-AA21-131A": (
        "$4.4M ransom paid. 45% of East Coast fuel supply, shut down for days."
    ),
    "CISA-AA20-352A": (
        "~18,000 organizations installed the trojanized Orion update."
    ),
    "MGM-2023-SEC-8K": (
        "~$100M hit to quarterly earnings. Las Vegas systems dark for days."
    ),
    "CVE-2021-44228": (
        "Critical RCE in Log4j — used by roughly two-thirds of Java apps worldwide."
    ),
    "NHS-WannaCry-NCSC-2017": (
        "One third of NHS England trusts disrupted. Thousands of appointments cancelled."
    ),
}


def upgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.add_column(sa.Column("real_world_stakes", sa.Text(), nullable=True))

    conn = op.get_bind()
    for source_ref, stakes in _STAKES_BY_SOURCE_REF.items():
        conn.execute(
            sa.text(
                "UPDATE scenarios SET real_world_stakes = :stakes "
                "WHERE source_reference = :ref"
            ),
            {"stakes": stakes, "ref": source_ref},
        )


def downgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_column("real_world_stakes")
