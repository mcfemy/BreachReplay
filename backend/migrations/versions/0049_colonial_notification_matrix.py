"""Phase 3 — Targeted Escalation & Notification Proportionality: Colonial
Pipeline notification matrix (item 5 of 5)

Revision ID: 0049_colonial_notification_matrix
Revises: 0048_nhs_notification_matrix
Create Date: 2026-09-05 00:00:00.000000

Fifth and final scenario in the build order (SolarWinds = 0038,
Log4Shell = 0042, MGM = 0047, NHS = 0048). Pure content-authoring
migration — zero verb_engine / action_engine changes.

Colonial's party list mixes in-scenario authored parties (CISA question
on gate-009, FBI on gate-010 / pressure-006, legal/compliance on
gate-007, CEO/Board/WSJ on pressure-005/007, ransom-as-strategy as the
explicit wrong path on gate-007) with one genuinely researched
addition: TSA under Security Directive Pipeline-2021-01. No Colonial
gate names TSA; SD Pipeline-2021-01 was issued May 2021 in direct
response to this incident and is the actual liquid-pipeline regulator
path (TSA/DHS → CISA within 12 hours), not NERC CIP.

Honesty note (same discipline as Log4Shell's CISA judgment call and
NHS's police-priority nuance): regulatory_frameworks currently lists
"NERC CIP", but NERC CIP governs the electric grid, not liquid
pipelines. This migration does NOT manufacture a NERC CIP party to
match that tag — the mismatch is flagged in the CISA and TSA party
rationales instead.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0049_colonial_notification_matrix"
down_revision: Union[str, None] = "0048_nhs_notification_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference — same convention as 0038/0042/0047/0048.
# Kept identical to seed.COLONIAL_PIPELINE["notification_matrix"] by hand.
_NOTIFICATION_MATRIX_BY_SOURCE_REF = {
    "CISA-AA21-131A": [  # Colonial Pipeline
        {
            "id": "cisa",
            "party_name": "CISA (mandatory reporting)",
            "warranted": True,
            "authority": "CISA (Cybersecurity and Infrastructure Security Agency)",
            "basis": "TSA Security Directive Pipeline-2021-01 (issued May 2021 in direct response to the Colonial Pipeline incident) — requires owner/operators of hazardous liquid and natural gas pipelines to report cybersecurity incidents to CISA within 12 hours of identification",
            "channel": "CISA incident reporting channel under SD Pipeline-2021-01",
            "window": "12 hours from identification of a cybersecurity incident",
            "rationale": "NERC CIP MISMATCH — regulatory_frameworks lists NERC CIP, but NERC CIP governs the electric grid, not liquid pipelines — Colonial's real regulator is TSA/DHS via SD Pipeline-2021-01, not NERC CIP. Do not invent a NERC CIP party to match that tag. gate-009's simultaneous pressure is Legal asking 'whether this triggers mandatory CISA reporting within hours' — the scenario authors the obligation generically. Verified real-world basis is more specific: TSA SD Pipeline-2021-01, issued May 2021 directly because of this incident, requires CISA notification within 12 hours. Scenario source_reference is already CISA-AA21-131A (the joint advisory on the DarkSide campaign).",
            "source_reference": "TSA Security Directive Pipeline-2021-01 (May 2021); this scenario's own gate-009 and source_reference CISA-AA21-131A",
        },
        {
            "id": "tsa",
            "party_name": "TSA (Cybersecurity Coordinator / SD Pipeline-2021-01)",
            "warranted": True,
            "authority": "TSA (Transportation Security Administration) / DHS — pipeline security",
            "basis": "TSA Security Directive Pipeline-2021-01 requires designated owner/operators to appoint a Cybersecurity Coordinator available to TSA and CISA 24/7; cybersecurity-incident reporting under the directive is TSA-mandated even when the notice channel is CISA",
            "channel": "TSA / Cybersecurity Coordinator liaison under SD Pipeline-2021-01",
            "window": "Immediate designation/availability; incident reporting aligned to the directive's 12-hour CISA clock",
            "rationale": "NERC CIP MISMATCH — regulatory_frameworks lists NERC CIP, but NERC CIP governs the electric grid, not liquid pipelines — Colonial's real regulator is TSA/DHS via SD Pipeline-2021-01, not NERC CIP. Do not manufacture a NERC CIP party to match that incorrect tag. ADDED VIA RESEARCH, not extracted from an authored gate — no Colonial gate or pressure names TSA explicitly. Distinguishes this party from CISA/FBI, which are directly authored in-scenario (gate-009 Legal CISA question; gate-010 / pressure-006 FBI coordination). SD Pipeline-2021-01 is the actual post-incident regulatory instrument for hazardous liquid pipeline cybersecurity; reporting under it is functionally TSA-mandated.",
            "source_reference": "TSA Security Directive Pipeline-2021-01 (May 2021) — Cybersecurity Coordinator and incident-reporting requirements; researched addition (not named in any gate)",
        },
        {
            "id": "fbi",
            "party_name": "FBI",
            "warranted": True,
            "authority": "FBI Cyber Division / joint cyber investigation",
            "basis": "Active FBI coordination during DarkSide ransomware against critical infrastructure — containment that preserves live C2 telemetry for attribution",
            "channel": "FBI Cyber Division liaison / joint coordination",
            "window": "Immediate upon confirmed ransomware staging / active federal liaison contact",
            "rationale": "Fully authored in-scenario: pressure-006 is Special Agent T. Reyes (FBI Cyber Division) demanding the containment plan before execution; gate-010's correct option is mass-isolate network access while leaving EDR telemetry and the C2 channel passively observed in parallel with the FBI. Consequence_if_correct: 'Detonation is prevented AND the live C2 trace gives the FBI what they need.'",
            "source_reference": "This scenario's own pressure-006 and gate-010 correct option",
        },
        {
            "id": "legal_compliance",
            "party_name": "Legal / compliance (scope before ransom decision)",
            "warranted": True,
            "authority": "Internal Legal / Compliance",
            "basis": "Confirmed 93GB exfiltration of financial records and network diagrams with unresolved question whether regulated customer data was included — notification obligations cannot be scoped without legal/compliance ownership",
            "channel": "Internal escalation to legal/compliance",
            "window": "Immediate upon confirmed exfiltration — before any ransom commitment",
            "rationale": "gate-007's correct option is explicitly: tell the CEO no ransom decision yet, first priority is determining what left and whether it includes regulated data, and loop in legal/compliance now. Consequence_if_correct: legal and compliance engaged early; breach-scope investigation runs in parallel with technical response. This is the scenario's own authored path for notification-scoping, not an addition.",
            "source_reference": "This scenario's own gate-007 correct option",
        },
        {
            "id": "ceo_board_public",
            "party_name": "CEO / Board / public statement (WSJ)",
            "warranted": True,
            "authority": "CEO / Board / public communications",
            "basis": "Public-company crisis escalation — Board and CEO demand exposure status, ransom posture, and signed public statement once WSJ contact and publication are live",
            "channel": "CEO briefing / Board escalation / approved public statement",
            "window": "Immediate — pressure-005 demands status in 5 minutes; pressure-007 demands personal sign-off on the public statement within thirty seconds of WSJ publication",
            "rationale": "pressure-005 is the CEO email demanding ransom/exposure status before WSJ publishes (or she calls the FBI herself); pressure-007 is the WSJ breaking story with the CEO demanding personal sign-off on the approved public statement. This is a legitimate internal/public-company escalation party, not a regulator — same class as NHS's Trust CEO/Board entry.",
            "source_reference": "This scenario's own pressure-005 and pressure-007",
        },
        {
            "id": "ransom_payment_strategy",
            "party_name": "Ransom payment as the notification / disclosure strategy",
            "warranted": False,
            "authority": "N/A — not a warranted notification path",
            "basis": "Paying ransom is not a notification or disclosure strategy — it is a premature operational/legal commitment made before scoping what was exfiltrated",
            "channel": "N/A — not warranted by this scenario's actual facts",
            "window": "N/A",
            "rationale": "gate-007 makes this exact call explicit: option 1 ('Tell the CEO yes, let's pay — it's the fastest path to limiting damage') is the WRONG answer. Consequence text: 'A premature commitment — the board now expects a ransom payment before anyone has confirmed what was taken or whether paying is even legal.' Treating ransom payment as the warranted notification/disclosure path would be the under-notification / integrity failure mode this mechanic exists to catch.",
            "source_reference": "This scenario's own gate-007 authored wrong option and consequence_if_chosen",
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
