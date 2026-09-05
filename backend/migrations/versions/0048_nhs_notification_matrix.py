"""Phase 3 — Targeted Escalation & Notification Proportionality: NHS WannaCry
notification matrix (item 4 of 5)

Revision ID: 0048_nhs_notification_matrix
Revises: 0047_mgm_notification_matrix
Create Date: 2026-09-05 00:00:00.000000

Fourth scenario in the build order (SolarWinds = 0038, Log4Shell = 0042,
MGM = 0047). Confirms the mechanism itself needed zero code changes to
extend — this is purely a content-authoring migration, same shape as
0042/0047.

NHS WannaCry's party list is deliberately DIFFERENT from the prior three —
not a reused CISA/PCI/SOC2 template. This scenario's own content
(backend/seed.py's NHS_WANNACRY dict) is UK healthcare ransomware with
confirmed availability impact and NO exfiltration
(regulatory_frameworks=["NHS DSP Toolkit", "ICO DPA 2018", ...]), so the
matrix is built around accurate ICO Article 33 characterization, NCSC
kill-switch authority, NHS England Major Incident coordination, Trust
CEO/Board escalation, a nuanced secondary police path, and the explicit
wrong path of filing ICO notice as a confirmed patient-data breach.

Real, retrievable citations, same sourcing bar as `hidden_iocs`:
- DPA 2018 / UK GDPR Article 33 72-hour notification — matches
  nhs-pressure-004's own email text exactly.
- NCSC as UK national cyber authority — matches nhs-gate-004's authored
  correct action on kill-switch intelligence.
- NHS Incident Response Framework / Major Incident + NHS England notify —
  matches nhs-gate-002's correct option.

One party is deliberately NOT warranted, grounded directly in this
scenario's own authored resolution: nhs-gate-005's wrong option is to
file confirming "a data breach affecting patient records" — consequence
text says this "creates a regulatory record that may misclassify
ransomware-as-availability-attack as a data breach." That's the exact
over-notification / integrity failure mode this mechanic exists to catch.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0048_nhs_notification_matrix"
down_revision: Union[str, None] = "0047_mgm_notification_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference — same convention as 0038/0042/0047.
# Kept identical to seed.NHS_WANNACRY["notification_matrix"] by hand.
_NOTIFICATION_MATRIX_BY_SOURCE_REF = {
    "NHS-WannaCry-NCSC-2017": [  # NHS WannaCry
        {
            "id": "ico_article_33",
            "party_name": "ICO (Article 33 — accurate characterization)",
            "warranted": True,
            "authority": "ICO (Information Commissioner's Office)",
            "basis": "DPA 2018 / UK GDPR Article 33 — controllers must notify the ICO of personal data breaches within 72 hours of becoming aware, with accurate scope characterization",
            "channel": "ICO incident-reporting channel / DPO response to formal enquiry",
            "window": "72 hours from becoming aware",
            "rationale": "nhs-gate-005's correct option is explicitly to inform the ICO that this is a ransomware availability attack with no evidence of data exfiltration — notification should reflect actual risk. Matches nhs-pressure-004's own Article 33 / 72-hour framing exactly, while refusing the over-classification that gate's wrong option would create.",
            "source_reference": "DPA 2018 / UK GDPR Article 33; this scenario's own nhs-gate-005 correct option and nhs-pressure-004",
        },
        {
            "id": "ncsc",
            "party_name": "NCSC",
            "warranted": True,
            "authority": "NCSC (National Cyber Security Centre) — UK national authority for cyber incident guidance",
            "basis": "NCSC is the UK's national technical authority for cyber incidents; WannaCry kill-switch and containment guidance was issued and verified through NCSC channels during the real May 2017 incident",
            "channel": "NCSC incident guidance / threat-intelligence coordination",
            "window": "Immediate upon receiving verified NCSC intelligence during active spread",
            "rationale": "nhs-gate-004 treats NCSC kill-switch intelligence as authoritative and correct to act on immediately — consequence_if_correct states allowing the kill-switch domain is the NCSC-recommended action. Trust in verified NCSC threat intelligence is the scenario's own authored IR discipline, not an addition.",
            "source_reference": "This scenario's own nhs-gate-004 (NCSC kill-switch intelligence); NCSC WannaCry guidance, May 2017",
        },
        {
            "id": "nhs_england",
            "party_name": "NHS England / Major Incident coordination",
            "warranted": True,
            "authority": "NHS England / NHS Incident Response Framework",
            "basis": "NHS Incident Response Framework — declaring a Major Incident activates practiced BCP, clinical fallback authority, and escalation to NHS England for multi-Trust coordination",
            "channel": "Major Incident declaration / NHS England notification under the Incident Response Framework",
            "window": "Immediate upon clinical systems at risk and uncontrolled ransomware spread",
            "rationale": "nhs-gate-002's correct option is explicitly 'Declare a Major Incident immediately — activate full BCP, move all clinical areas to paper-based fallback, notify NHS England.' Consequence text states this starts the regulatory notification clock properly and is compliant with the NHS Incident Framework.",
            "source_reference": "NHS Incident Response Framework; this scenario's own nhs-gate-002 correct option",
        },
        {
            "id": "trust_ceo_board",
            "party_name": "Trust CEO / Board",
            "warranted": True,
            "authority": "Trust Chief Executive / Board of Directors",
            "basis": "Clinical governance escalation — Board-level awareness is required before and during Major Incident / regulatory notification decisions that create Trust-wide exposure",
            "channel": "Direct CEO briefing ahead of Board notification",
            "window": "Immediate — nhs-pressure-001 demands answers in 10 minutes before the CEO calls the Board",
            "rationale": "nhs-pressure-001 is a live CEO email demanding a legal-exposure briefing before informing the Board: patient-data theft risk, ICO obligation, and police contact. Clinical governance requires this escalation path; the scenario authors it as simultaneous pressure on nhs-gate-002, not as optional courtesy.",
            "source_reference": "This scenario's own nhs-pressure-001 and nhs-gate-002 simultaneous pressure",
        },
        {
            "id": "police_data_theft",
            "party_name": "Police (as a \"data theft\" crime report)",
            "warranted": True,
            "authority": "Police / Action Fraud (cyber crime reporting)",
            "basis": "CEO question in nhs-pressure-001 raises police contact, but no gate resolves a data-theft crime report as first-priority action — forensics show availability impact only, not confirmed exfiltration",
            "channel": "Police / Action Fraud cyber-crime reporting (if pursued)",
            "window": "Secondary — after ICO accurate characterization, NCSC guidance, and NHS England Major Incident coordination",
            "rationale": "WARRANTED, BUT NOT FIRST-PRIORITY — do not read this entry as equal in urgency to ICO Article 33 accuracy, NCSC guidance, or NHS England Major Incident coordination. GENUINE JUDGMENT CALL: nhs-pressure-001's CEO asks 'should we contact the police?' but no gate makes a data-theft crime report the correct first move. nhs-gate-005 confirms no evidence of patient-data exfiltration — treating this primarily as a data-theft crime report would be premature ahead of the ICO / NCSC / NHS England response. Warranted only as a legitimate secondary path (law-enforcement awareness of Trust-disrupting ransomware remains reasonable after those primary notifications), not as a co-equal or first-wave obligation.",
            "source_reference": "This scenario's own nhs-pressure-001 (CEO police question) and nhs-gate-005 (no exfiltration)",
        },
        {
            "id": "ico_confirmed_breach",
            "party_name": "ICO notification framed as confirmed patient-data breach / exfiltration",
            "warranted": False,
            "authority": "N/A — not a warranted notification path",
            "basis": "Filing an ICO notification that confirms a patient-data breach / exfiltration when forensics show encryption without exfiltration misclassifies an availability incident as a personal data breach",
            "channel": "N/A — not warranted by this scenario's actual facts",
            "window": "N/A",
            "rationale": "nhs-gate-005 makes this exact call explicit: option 0 ('File an ICO notification now confirming a data breach affecting patient records') is the WRONG answer. Consequence text states this 'creates a regulatory record that may misclassify ransomware-as-availability-attack as a data breach, with downstream consequences.' Treating confirmed-breach framing as warranted would be the over-notification / integrity failure mode this mechanic exists to catch.",
            "source_reference": "This scenario's own nhs-gate-005 authored wrong option and consequence_if_chosen",
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
