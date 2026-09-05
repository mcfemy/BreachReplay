"""Phase 3 — Targeted Escalation & Notification Proportionality: MGM Resorts
notification matrix (item 3 of 5)

Revision ID: 0047_mgm_notification_matrix
Revises: 0046_response_index
Create Date: 2026-09-05 00:00:00.000000

Third scenario in the build order (SolarWinds = 0038, Log4Shell = 0042).
Confirms the mechanism itself needed zero code changes to extend — this is
purely a content-authoring migration, same shape as 0042's.

MGM's party list is deliberately DIFFERENT from SolarWinds' and
Log4Shell's — not a reused CISA/DC3/SOC2/customer template. This
scenario's own content (backend/seed.py's MGM_GRAND dict) is hospitality
ransomware with confirmed payment-card theft
(regulatory_frameworks=["PCI-DSS", "NIST CSF"]), so the matrix is built
around PCI card-brand reporting, FBI engagement on Scattered Spider,
guest breach notice, and the SEC Item 1.05 8-K clock that
mgm-pressure-004 already authors in-scenario.

Real, retrievable citations, same sourcing bar as `hidden_iocs`:
- PCI-DSS account-data-compromise reporting for confirmed PAN exposure
  (mgm-gate-005 correct option + SIEM-411).
- CISA Alert AA23-320A (Scattered Spider) — the verified joint advisory
  naming the threat group behind the real MGM September 2023 incident.
- SEC 2023 cybersecurity disclosure rule / Form 8-K Item 1.05 (effective
  December 2023) — matches mgm-pressure-004's own claim exactly; scenario
  source_reference is already MGM-2023-SEC-8K.

One party is deliberately NOT warranted, grounded directly in this
scenario's own authored resolution: mgm-gate-005's wrong options are pay
or negotiate while delaying disclosure — named in-scenario as the
"Caesars strategy" that "creates additional legal exposure." That's the
exact under-notification / integrity failure mode this mechanic exists
to catch, already authored in-scenario rather than invented for this
migration.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0047_mgm_notification_matrix"
down_revision: Union[str, None] = "0046_response_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Matched by scenarios.source_reference — same convention as 0038/0042.
# Kept identical to seed.MGM_GRAND["notification_matrix"] by hand.
_NOTIFICATION_MATRIX_BY_SOURCE_REF = {
    "MGM-2023-SEC-8K": [  # MGM Resorts
        {
            "id": "pci_card_brands",
            "party_name": "PCI Council / card brands",
            "warranted": True,
            "authority": "PCI Security Standards Council / payment card brands (Visa, Mastercard, Amex, Discover)",
            "basis": "PCI-DSS breach notification obligations for compromised payment card data — account data compromise (ADC) reporting to acquiring banks and card brands when full PANs are confirmed exposed",
            "channel": "Acquiring bank / card-brand account-data-compromise reporting channels",
            "window": "Immediately upon confirmed PAN exposure — brand programs typically require prompt ADC reporting",
            "rationale": "mgm-gate-005's correct option is explicitly 'notify PCI-DSS card brands immediately'; the scenario's own SIEM-411 alert confirms a PCI-DSS breach with 1,000 full PAN numbers (plus CVV/name/address) published on a dark web forum. This is a live card-brand reporting trigger, not a hypothetical.",
            "source_reference": "PCI-DSS account-data-compromise reporting obligations; this scenario's own mgm-gate-005 correct option and SIEM-411 alert",
        },
        {
            "id": "fbi",
            "party_name": "FBI",
            "warranted": True,
            "authority": "FBI (Federal Bureau of Investigation) / cyber crime investigation",
            "basis": "FBI engagement on confirmed ransomware with published payment-card theft — grounded in the real FBI/CISA joint advisory on Scattered Spider (AA23-320A), the named threat group behind MGM's real September 2023 incident",
            "channel": "FBI field office / Internet Crime Complaint Center (IC3) cyber incident reporting",
            "window": "As soon as practicable upon confirmed ransomware and published cardholder data",
            "rationale": "mgm-gate-005's correct option is explicitly 'engage FBI'; consequence text notes FBI engagement may provide tactical information about the attacker group. Real-world grounding: CISA advisory AA23-320A (Scattered Spider) is the verified joint advisory naming the threat group behind the real MGM 2023 compromise — same campaign this scenario replays.",
            "source_reference": "CISA Alert AA23-320A (Scattered Spider); this scenario's own mgm-gate-005 correct option",
        },
        {
            "id": "affected_guests",
            "party_name": "Affected guests / customer notification",
            "warranted": True,
            "authority": "Affected guests whose payment-card and personal data were exposed",
            "basis": "Standard U.S. state breach-notification statutes and PCI-adjacent customer-notice practice when full PANs plus name/address are confirmed published",
            "channel": "Direct customer notification (mail/email) per applicable state breach-notification law and card-brand guidance",
            "window": "Per applicable state statute — typically without unreasonable delay once the breach is confirmed",
            "rationale": "mgm-gate-005's correct option is explicitly 'begin customer notification'; consequence text states customer notification is 'painful but legally required.' SIEM-411 confirms exposure of full_PAN, CVV, name, and address for 1,000 guest records — the exact trigger class for consumer breach notice.",
            "source_reference": "This scenario's own mgm-gate-005 correct option and SIEM-411 alert (full_PAN/CVV/name/address)",
        },
        {
            "id": "sec",
            "party_name": "SEC / securities counsel (Item 1.05 Form 8-K)",
            "warranted": True,
            "authority": "U.S. Securities and Exchange Commission — Form 8-K Item 1.05 (Material Cybersecurity Incidents)",
            "basis": "SEC 2023 cybersecurity disclosure rule (effective December 2023): public companies must disclose a material cybersecurity incident on Form 8-K Item 1.05 within four business days of determining materiality",
            "channel": "Form 8-K Item 1.05 filing via securities counsel",
            "window": "4 business days from materiality determination",
            "rationale": "mgm-pressure-004 is a live securities-counsel email stating exactly this clock: 'if this is a material cybersecurity incident under the new SEC rules (effective December 2023), we have 4 business days to file an 8-K.' Confirmed PAN publication and property-wide ransomware are the class of event that materiality assessment exists for. Scenario source_reference is already MGM-2023-SEC-8K.",
            "source_reference": "SEC cybersecurity disclosure rule (Item 1.05 Form 8-K, effective Dec 2023); this scenario's own mgm-pressure-004 and source_reference MGM-2023-SEC-8K",
        },
        {
            "id": "legal",
            "party_name": "Internal General Counsel",
            "warranted": True,
            "authority": "Internal General Counsel / securities counsel",
            "basis": "Confirmed PCI-DSS breach plus a running SEC Item 1.05 materiality clock creates disclosure-controls and mandatory-reporting obligations that require legal ownership independent of any single outside agency notice",
            "channel": "Internal escalation",
            "window": "Immediate upon confirmed PAN publication / materiality assessment demand",
            "rationale": "mgm-pressure-004 already has SEC Regulatory Counsel demanding a written incident characterization within 2 hours, and mgm-gate-005's simultaneous pressure is that same securities-counsel clock. Legal involvement is the scenario's own authored path for both PCI and SEC obligations — not an addition.",
            "source_reference": "This scenario's own mgm-pressure-004 and mgm-gate-005",
        },
        {
            "id": "caesars_quiet_payment",
            "party_name": "Quiet/delayed disclosure while paying ransom (\"Caesars strategy\")",
            "warranted": False,
            "authority": "N/A — not a warranted notification path",
            "basis": "Paying ransom while quietly assessing disclosure (or negotiating without committing) delays mandatory notice and does not guarantee data deletion — the scenario's own authored wrong paths",
            "channel": "N/A — not warranted by this scenario's actual facts",
            "window": "N/A",
            "rationale": "mgm-gate-005 makes this exact call explicit: options 1 and 2 (pay while quietly assessing disclosure; negotiate without committing) are the WRONG answers. The scenario names the pay-and-stay-quiet approach as what Caesars Entertainment did two weeks earlier ('later disclosed publicly') and states delayed disclosure while paying 'creates additional legal exposure.' Treating quiet payment/delay as warranted would be the under-notification / integrity failure mode this mechanic exists to catch.",
            "source_reference": "This scenario's own mgm-gate-005 authored wrong options and consequence_if_wrong",
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
