"""Phase 3 — Targeted Escalation & Notification Proportionality: Log4Shell
notification matrix (item 2 of 5)

Revision ID: 0042_log4shell_notification_matrix
Revises: 0041_action_run_public_share
Create Date: 2026-08-11 00:00:00.000000

Second scenario in the build order (SolarWinds was item 1, migration 0038).
Originally authored as 0039 revising 0038; renumbered to 0042 on rebase so
it chains after technique_encounters / verb-coachmarks / public-share
rather than forking a second head off 0038. Confirms the mechanism itself
needed zero code changes to extend — this is purely a content-authoring
migration, same shape as 0038's.

Log4Shell's party list is deliberately DIFFERENT from SolarWinds' — not a
reused DC3/CISA/prime/insurer/legal/PR template. This scenario's own
content (backend/seed.py's LOG4SHELL dict) has no FedRAMP/CMMC/government-
contract framing at all (regulatory_frameworks is just ["NIST CSF",
"SOC 2"], industry_vertical "technology") — a generic tech vendor to
enterprise customers, not a DIB contractor. DC3 doesn't fit this
scenario's fiction and isn't included.

Real, retrievable citations, same sourcing bar as `hidden_iocs`:
- CISA/FBI/NSA/international-partner joint advisory on mitigating
  Log4Shell (Dec 2021) — cited by agency/date/subject; exact advisory
  number flagged for expert-review verification rather than asserted
  with unverified precision (same discipline as 0038's SEC docket-number
  caveat).
- SOC 2 Type II / AICPA Trust Services Criteria — the exact contractual
  mechanism this scenario's own `log4-pressure-003` (Legal/Jennifer
  Walsh) already dialogues about: "47 enterprise customers with SOC 2
  Type II contracts containing a 72-hour breach notification clause."
- Standard B2B vendor security-incident notification clauses — grounded
  in `log4-pressure-002` (Meridian Financial Group's CISO threatening to
  invoke their own contractual clause).

One party is explicitly flagged as a genuine judgment call (CISA
voluntary reporting) rather than authored with false confidence — no
binding federal directive applies to a private tech company the way
ED-21-01 applied to SolarWinds' federal-adjacent org in 0038. And one
party is deliberately NOT warranted, grounded directly in this
scenario's own authored resolution: `log4-gate-005`'s correct answer is
to treat a 65%-confidence Hafnium APT attribution as a hypothesis to
investigate, not a fact to act on — the wrong-choice consequence text
says escalating to nation-state IR protocol "wastes massive resources on
a likely false positive" (it's a copycat cryptominer C2). That's the
exact over-notification failure mode this mechanic exists to catch,
already authored in-scenario rather than invented for this migration.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0042_log4shell_notification_matrix"
down_revision: Union[str, None] = "0041_action_run_public_share"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference — same convention as 0038/0034.
_NOTIFICATION_MATRIX_BY_SOURCE_REF = {
    "CVE-2021-44228": [  # Log4Shell
        {
            "id": "customer_contractual",
            "party_name": "Enterprise customers under contractual notification clauses",
            "warranted": True,
            "authority": "Contracted enterprise customers (e.g. Meridian Financial Group)",
            "basis": "Standard B2B vendor security-incident notification clauses in customer master service agreements",
            "channel": "Direct written notice per the contract's incident-notification clause",
            "window": "Per the contract — typically 24-72 hours from confirmed impact",
            "rationale": "log4-pressure-002 has Meridian's CISO explicitly threatening to invoke their own contractual incident notification clause. Confirmed exploitation of customer-facing API infrastructure (WAF-089's 847 blocked JNDI requests against api-gateway.prod.internal) makes this a live contractual trigger, not a hypothetical.",
            "source_reference": "This scenario's own log4-pressure-002 (Meridian Financial Group)",
        },
        {
            "id": "soc2_customers",
            "party_name": "SOC 2 Type II customer base",
            "warranted": True,
            "authority": "47 enterprise customers under SOC 2 Type II contracts",
            "basis": "SOC 2 Type II / AICPA Trust Services Criteria — customer contracts' own 72-hour breach notification clause",
            "channel": "Per each customer contract's designated notification channel",
            "window": "72 hours from confirmed customer-data exposure",
            "rationale": "log4-gate-005's own pressure event (Legal — Jennifer Walsh) states this exactly: '47 enterprise customers with SOC 2 Type II contracts containing a 72-hour breach notification clause... the clock may already be running.' Confirmed active exploitation (reverse shell, cryptominers, a staged Cobalt Strike beacon) across production Java services is the class of event that clause exists for.",
            "source_reference": "SOC 2 Type II / AICPA Trust Services Criteria; this scenario's own log4-pressure-003",
        },
        {
            "id": "legal",
            "party_name": "Internal General Counsel",
            "warranted": True,
            "authority": "Internal General Counsel",
            "basis": "Confirmed active exploitation across multiple production services with unresolved customer-data exposure scope creates disclosure-controls review obligations independent of any single named statute",
            "channel": "Internal escalation",
            "window": "Immediate upon confirmed exploitation",
            "rationale": "log4-pressure-003 already has Legal (Jennifer Walsh) as the one demanding exposure scope for exactly this reason — legal involvement is the scenario's own authored correct path, not an addition.",
            "source_reference": "This scenario's own log4-pressure-003 (Legal — Jennifer Walsh)",
        },
        {
            "id": "pr_comms",
            "party_name": "PR / Communications",
            "warranted": True,
            "authority": "Internal PR / Communications",
            "basis": "Not a legal requirement — crisis-communications best practice once a reporter is already actively investigating, to avoid an information vacuum a hostile story would fill instead",
            "channel": "Prepared public statement / holding response",
            "window": "Before the reporter's stated publication deadline",
            "rationale": "log4-pressure-004 has a TechCrunch security reporter already citing specific scan evidence (JNDI error responses from this org's own API endpoints) and a same-morning publication deadline — this is not a hypothetical media-exposure risk, it is already in progress. Flagged honestly as best-practice, not a statute, same discipline as SolarWinds' cyber-insurer entry.",
            "source_reference": "This scenario's own log4-pressure-004 (TechCrunch security reporter)",
        },
        {
            "id": "cisa",
            "party_name": "CISA (voluntary threat/incident information sharing)",
            "warranted": True,
            "authority": "CISA (Cybersecurity and Infrastructure Security Agency)",
            "basis": "CISA (jointly with FBI, NSA, and international partners) published guidance on mitigating Log4Shell in December 2021 and encouraged voluntary reporting of related compromises given the vulnerability's unprecedented internet-wide severity",
            "channel": "CISA's voluntary incident-reporting channel",
            "window": "As soon as practicable — voluntary, no binding deadline",
            "rationale": "GENUINE JUDGMENT CALL, flagged explicitly rather than authored with false confidence (same treatment SolarWinds' matrix gave DC3): unlike SolarWinds' scenario, nothing here establishes the org as a federal agency or federal contractor — regulatory_frameworks is just NIST CSF/SOC 2, no FedRAMP/CMMC, no ED-21-01-equivalent binding directive applies. Authored as warranted on the strength of CISA's own public posture toward Log4Shell specifically (a 10/10 CVSS vulnerability affecting hundreds of millions of systems, an unusually urgent joint advisory) rather than any binding legal requirement. Marked for expert review before treating this as settled.",
            "source_reference": "CISA/FBI/NSA joint advisory on mitigating Log4Shell, Dec 2021 — exact advisory number pending expert-review verification, cited by agency/subject/date rather than an unverified precise identifier",
        },
        {
            "id": "dhs_nation_state",
            "party_name": "DHS / nation-state incident-response protocol",
            "warranted": False,
            "authority": "DHS nation-state incident-response coordination",
            "basis": "Escalating to formal nation-state IR protocol requires confirmed attribution, not an unconfirmed, moderate-confidence threat-intelligence hypothesis",
            "channel": "N/A — not warranted by this scenario's actual facts",
            "window": "N/A",
            "rationale": "log4-gate-005 makes this exact call explicit in its own authored resolution: the Hafnium APT beacon on app-svr-03 is 65% confidence, and the CORRECT response is to isolate and investigate as a hypothesis, not act on it as fact — the wrong-choice consequence text says escalating to nation-state IR protocol 'wastes massive resources on a likely false positive' (forensics confirm it's a copycat cryptominer C2, not Hafnium). Treating this as warranted would be the over-notification failure mode this mechanic exists to catch.",
            "source_reference": "This scenario's own log4-gate-005 authored resolution",
        },
    ],
}


def upgrade() -> None:
    bind = op.get_bind()

    matrix_col_type = JSONB if bind.dialect.name == "postgresql" else sa.JSON
    matrix_stmt = sa.text(
        "UPDATE scenarios SET notification_matrix = :matrix WHERE source_reference = :ref"
    ).bindparams(sa.bindparam("matrix", type_=matrix_col_type), sa.bindparam("ref", type_=sa.String))
    for source_ref, matrix in _NOTIFICATION_MATRIX_BY_SOURCE_REF.items():
        bind.execute(matrix_stmt, {"matrix": matrix, "ref": source_ref})


def downgrade() -> None:
    bind = op.get_bind()

    matrix_col_type = JSONB if bind.dialect.name == "postgresql" else sa.JSON
    clear_stmt = sa.text(
        "UPDATE scenarios SET notification_matrix = :empty WHERE source_reference = :ref"
    ).bindparams(sa.bindparam("empty", type_=matrix_col_type), sa.bindparam("ref", type_=sa.String))
    for source_ref in _NOTIFICATION_MATRIX_BY_SOURCE_REF:
        bind.execute(clear_stmt, {"empty": [], "ref": source_ref})
