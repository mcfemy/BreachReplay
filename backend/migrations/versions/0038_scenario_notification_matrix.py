"""Phase 3 — Targeted Escalation & Notification Proportionality: per-scenario
authored notification matrix

Revision ID: 0038_scenario_notification_matrix
Revises: 0037_cmmc_issued_evidence_packs
Create Date: 2026-08-10 00:00:00.000000

`scenarios.notification_matrix` (new JSONB list column) — the scenario's own
authored ground truth for which parties a warranted notification decision
covers, replacing the old free/untargeted/one-shot `escalate` verb's total
lack of per-party data (see docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md
section 10, the item that flagged this as a Phase 3 follow-up).

Deliberately NOT the same thing as `ClientOrg.notification_matrix` (Phase
2.5 item 4) — that's the client org's own generically-declared contact
policy (authority/basis/channel/window, org-wide, no incident-specific
judgment). This column is BreachReplay's own authored, scenario-specific
"was notifying this party actually warranted given this incident's facts"
judgment, following the same `regulatory_frameworks`/`collateral_weights`
precedent: per-scenario authored content, not a client declaration.

Same field-shape choice as item 4's matrix (authority/basis/channel/window)
plus `id`/`warranted`/`rationale`/`source_reference` — reusing the schema
readers of the CMMC evidence pack already recognize, not inventing a new
shape for `_notifications_html` to learn.

SolarWinds only in this migration — the reference-implementation scenario
per the Phase 3 build order (it already has the most FedRAMP/DC3-adjacent
content authored, per gate-006's GC dialogue and the ED-21-01 gates). The
other 4 flagship scenarios get their own matrices in follow-up work, each
needing its own regulator-appropriate party list (MGM: PCI Council/card
brands/FBI; Colonial: TSA/NERC CIP; NHS: ICO/NCSC; Log4Shell: SOC 2/
customer contractual clauses) — see docs/BACKLOG.md.

Every citation below is a real, retrievable source (CISA Emergency
Directive 21-01, DFARS 252.204-7012, the SEC's 2023 SolarWinds
disclosure-controls action), same sourcing bar as `hidden_iocs`'
descriptions. The one deliberately NOT-warranted entry
(state-AG/consumer-breach regulators) is grounded directly in this
scenario's own already-authored sol-gate-007 resolution ("Orion monitored
network devices, not personal data... a serious overreaction") rather than
invented — the exact over-notification failure mode this mechanic exists
to catch.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0038_scenario_notification_matrix"
down_revision: Union[str, None] = "0037_cmmc_issued_evidence_packs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference, same key/convention as 0034's
# _COLLATERAL_WEIGHTS_BY_SOURCE_REF — kept in sync with seed.py's
# SOLARWINDS["notification_matrix"] by hand for the same reason 0034's
# comment explains (seed.py's seed() only inserts new rows, never updates
# existing ones).
_NOTIFICATION_MATRIX_BY_SOURCE_REF = {
    "CISA-AA20-352A": [  # SolarWinds
        {
            "id": "cisa",
            "party_name": "CISA",
            "warranted": True,
            "authority": "CISA (Cybersecurity and Infrastructure Security Agency)",
            "basis": "CISA Emergency Directive 21-01, issued Dec 13, 2020, ordering every federal civilian agency running SolarWinds Orion to disconnect immediately and report compliance status",
            "channel": "CISA incident coordination line / ED-21-01 compliance reporting",
            "window": "Immediate — a binding emergency directive, not a discretionary notification",
            "rationale": "sol-gate-005 and sol-gate-007 are built directly on ED-21-01's real disconnect-and-report requirement. An organization subject to it that doesn't coordinate with CISA is non-compliant with a binding federal order, not just slow.",
            "source_reference": "CISA Emergency Directive 21-01 (ED-21-01), Dec 13 2020",
        },
        {
            "id": "dc3",
            "party_name": "DC3 (DoD Cyber Crime Center)",
            "warranted": True,
            "authority": "DC3 (DoD Cyber Crime Center)",
            "basis": "DFARS 252.204-7012 — a DoD contractor whose covered information system may have been affected by a cyber incident must report to DC3 within 72 hours of discovery",
            "channel": "DIBNet portal (dibnet.dod.mil)",
            "window": "72 hours from discovery",
            "rationale": "sol-pressure-004 (General Counsel: 'Do we have any government contracts? FedRAMP customers? ... mandatory breach notification obligations') establishes the org as holding federal/DoD-adjacent contracts in this scenario's fiction. With domain admin credentials and 90 days of CISO mailbox access confirmed compromised, a DFARS-covered organization has clearly crossed the reporting threshold.",
            "source_reference": "DFARS 252.204-7012",
        },
        {
            "id": "legal",
            "party_name": "Internal General Counsel",
            "warranted": True,
            "authority": "Internal General Counsel",
            "basis": "A confirmed nation-state compromise with 90 days of CISO-mailbox access and domain admin credential exposure creates disclosure-controls and materiality-assessment obligations regardless of any single named statute",
            "channel": "Internal escalation",
            "window": "Immediate upon confirmed compromise",
            "rationale": "sol-gate-006 already has General Counsel demanding scope 'for mandatory disclosure decisions' as the scenario's own authored correct path. Real-world grounding, not proof this fictional org faces the same claim: the real SolarWinds Corp. and its CISO were later charged by the SEC (Oct 2023) over cybersecurity disclosure controls tied to this exact incident — flagged for the expert-review pass rather than cited with a specific docket number not independently verified.",
            "source_reference": "SEC v. SolarWinds Corp. and Timothy G. Brown (S.D.N.Y., charges filed Oct 30, 2023) — cite verified generally, exact docket number pending expert review",
        },
        {
            "id": "insurer",
            "party_name": "Cyber insurance carrier",
            "warranted": True,
            "authority": "Cyber insurance carrier",
            "basis": "Standard cyber policy notice-of-circumstance clauses typically require notifying the carrier promptly upon discovering a potential covered incident, well before the full claim is quantified",
            "channel": "Carrier's incident-notification hotline / broker",
            "window": "Per policy — typically \"as soon as practicable\" upon discovery",
            "rationale": "Policy-dependent rather than a specific statute — flagged honestly as such, not overstated. A confirmed nation-state breach with credential and mailbox compromise is exactly the class of event that triggers a notice-of-circumstance duty under nearly every commercial cyber policy.",
            "source_reference": "Standard cyber-insurance notice-of-circumstance practice (policy-specific, not a named statute)",
        },
        {
            "id": "prime",
            "party_name": "Prime contractor(s) / downstream contract counterparties",
            "warranted": True,
            "authority": "Prime contractor(s) / contracted downstream customers",
            "basis": "DFARS 252.204-7012(m) requires a prime to flow the same reporting obligation down to subcontractors; a sub who discovers a covered incident must inform its prime",
            "channel": "Direct contractual notice per the flow-down clause",
            "window": "Per the flow-down clause — typically aligned to the 72-hour DC3 window",
            "rationale": "The scenario's FedRAMP/government-contract framing (sol-pressure-004) implies contractual relationships carrying flow-down reporting duties, not just a direct-to-government obligation.",
            "source_reference": "DFARS 252.204-7012(m)",
        },
        {
            "id": "state_ag",
            "party_name": "State Attorneys General (consumer breach-notification statutes)",
            "warranted": False,
            "authority": "State Attorneys General (consumer data-breach notification statutes)",
            "basis": "State breach-notification laws are triggered by unauthorized access to consumer personal information specifically — not by compromise of network-management infrastructure alone",
            "channel": "N/A — not triggered in this scenario",
            "window": "N/A",
            "rationale": "sol-gate-007 makes this exact call explicit in its own authored resolution: 'Orion monitored network devices, not personal data... a serious overreaction.' No consumer PII was confirmed exfiltrated — only network diagrams, credentials, and CISO mailbox contents. Notifying consumer-breach regulators here is the over-notification failure mode this mechanic exists to catch.",
            "source_reference": "This scenario's own sol-gate-007 authored resolution",
        },
    ],
}


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "scenarios",
        sa.Column(
            "notification_matrix",
            JSONB().with_variant(sa.JSON, "sqlite"),
            nullable=False,
            server_default="[]",
        ),
    )

    matrix_col_type = JSONB if bind.dialect.name == "postgresql" else sa.JSON
    matrix_stmt = sa.text(
        "UPDATE scenarios SET notification_matrix = :matrix WHERE source_reference = :ref"
    ).bindparams(sa.bindparam("matrix", type_=matrix_col_type), sa.bindparam("ref", type_=sa.String))
    for source_ref, matrix in _NOTIFICATION_MATRIX_BY_SOURCE_REF.items():
        bind.execute(matrix_stmt, {"matrix": matrix, "ref": source_ref})


def downgrade() -> None:
    op.drop_column("scenarios", "notification_matrix")
