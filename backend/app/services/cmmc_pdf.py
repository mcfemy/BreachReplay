"""Phase 2.5 CMMC Evidence Layer — evidence pack PDF generation (build-order
item 6).

Reuses reportlab (already a dependency, per app/services/cert_service.py)
but builds on `reportlab.platypus` (SimpleDocTemplate + flowables), not
cert_service.py's raw `canvas` API — that API is right for a one-page,
fixed-layout certificate; it gives no pagination or table layout for a
12-section, variable-length report (a timeline can have dozens of rows).

Visual identity is deliberately NOT cert_service.py's dark, gamified
badge look. Spec section 7's own instruction: "Tone: assessor-facing,
plain, no marketing." A cert is a player-facing achievement; this is an
audit document a third party has to actually read and trust. White
background, black/gray text, and colour used only functionally (red for
"Not Evidenced," matching how it's visually distinguished, never
decoratively).

Two deliberate honesty mechanisms, both reported and approved before this
was written:
- §8 Notifications renders the declared matrix and the escalation log as
  two SEPARATE tables, never joined — a merged table would visually imply
  a mapping the data doesn't support.
- §11 Control mapping is a real `evidenced` column, not prose — see
  build_control_mapping's docstring for the exact claims and why only
  control 3.6.3 is mapped in this build.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.scenario import Scenario
from app.services import action_engine
from app.services.cmmc_evidence import build_evidence_session_aggregate, runs_with_participant_names

_RED = colors.HexColor("#b91c1c")
_GREEN = colors.HexColor("#15803d")
_GRAY = colors.HexColor("#4b5563")
_LIGHT_GRAY = colors.HexColor("#e5e7eb")


def build_control_mapping() -> list[dict]:
    """The claims this pack does and does not stand behind, structural
    (evidenced: bool) rather than prose — approved design, per Femi's
    review: "'Notifications made per declared obligations — No' is more
    useful than a paragraph that buries it."

    Only control 3.6.3 is mapped in this build — including 3.6.1/3.6.2/
    AT-family "where genuinely exercised" (spec's own conditional
    inclusion) needs a real heuristic for "genuinely" that nothing in the
    current data model computes reliably. Guessing would itself be the
    padding this whole mechanism exists to prevent."""
    return [
        {
            "control": "3.6.3",
            "claim": "Incident detected, responded to, and reviewed via a documented after-action process with dual attestation",
            "evidenced": True,
            "note": "Timeline, outcomes, lessons, remediation, and both signatures all evidence this directly.",
        },
        {
            "control": "3.6.3",
            "claim": "Investigative actions evidenced by verb, target, and timing",
            "evidenced": True,
            "note": "Every logged action is attributed and timestamped.",
        },
        {
            "control": "3.6.3",
            "claim": "Investigative actions substantiated by captured tool output",
            "evidenced": False,
            "note": "The specific tool output shown to the responder is not persisted.",
        },
        {
            "control": "3.6.3",
            "claim": "Specific indicators of compromise identified during response",
            "evidenced": False,
            "note": "Only aggregate found/total counts are evidenced; specific indicator identities are not persisted.",
        },
        {
            "control": "3.6.3",
            "claim": "Notifications made per the organization's declared obligations",
            "evidenced": False,
            "note": "That an escalation occurred is evidenced; which declared obligation it satisfied, if any, is not.",
        },
    ]


async def build_pack_payload(
    db: AsyncSession,
    session: EvidenceSession,
    consulting_org: ConsultingOrg,
    client_org: ClientOrg,
    scenario: Scenario,
) -> dict:
    """Gathers everything generate_evidence_pack_pdf needs to render, from
    data already persisted by items 1-5 — no new instrumentation. Attacker
    stage progression is recomputed here (not stored anywhere) via
    action_engine.compile_scenario(scenario, run.seed) — a verified-pure
    function of data already on the ActionRun/Scenario rows."""
    aggregate = await build_evidence_session_aggregate(db, session)

    runs_result = await db.execute(select(ActionRun).where(ActionRun.evidence_session_id == session.id))
    runs = list(runs_result.scalars().all())
    run_summaries = await runs_with_participant_names(db, runs)
    names_by_run_id = {r["id"]: r["participant_name"] for r in run_summaries}

    attacker_stages = []
    for run in runs:
        compiled = action_engine.compile_scenario(scenario, run.seed)
        stage_rows = []
        for stage in compiled.stages:
            hostnames = []
            for host_id in stage.compromises_host_ids:
                host = compiled.world.get_host(host_id)
                hostnames.append(host.hostname if host is not None else host_id)
            stage_rows.append({
                "trigger_seconds": stage.trigger_seconds,
                "kind": stage.kind,
                "mitre_technique": stage.mitre_technique,
                "is_final": stage.is_final,
                "compromised_hostnames": hostnames,
            })
        attacker_stages.append({
            "run_id": run.id,
            "participant_name": names_by_run_id.get(run.id, "Unknown participant"),
            "mode": run.mode,
            "duration_seconds": run.duration_seconds,
            "stages": stage_rows,
        })

    return {
        "document_id": str(uuid.uuid4()),
        "consulting_org": {"name": consulting_org.name, "branding": consulting_org.branding},
        "client_org": {"name": client_org.name},
        "scenario": {
            "title": scenario.title,
            "source_type": scenario.source_type,
            "source_reference": scenario.source_reference,
            "source_url": scenario.source_url,
            "incident_date": scenario.incident_date,
        },
        "session": {
            "title": session.title,
            "exercise_date": session.exercise_date,
            "created_at": session.created_at,
        },
        "aggregate": aggregate,
        "attacker_stages": attacker_stages,
        "lessons_learned": session.lessons_learned,
        "remediation_items": session.remediation_items,
        "notification_matrix": client_org.notification_matrix,
        "irp_reference": client_org.irp_reference,
        "client_signoff": session.client_signoff,
        "consultant_signoff": session.consultant_signoff,
        "control_mapping": build_control_mapping(),
    }


# ── rendering ────────────────────────────────────────────────────────────

def _fmt_dt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%B %d, %Y %H:%M UTC")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("PackTitle", fontSize=20, leading=24, spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("SectionHeading", fontSize=14, leading=18, spaceBefore=14, spaceAfter=8, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("Body", fontSize=9.5, leading=13, textColor=colors.black))
    styles.add(ParagraphStyle("Note", fontSize=8.5, leading=12, textColor=_GRAY, spaceAfter=8))
    return styles


def _table(rows: list[list[str]], col_widths: Optional[list[float]] = None) -> Table:
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _cover_section(payload: dict, styles) -> list:
    consulting_name = payload["consulting_org"]["name"]
    client_name = payload["client_org"]["name"]
    story = [
        Spacer(1, 3 * cm),
        Paragraph("CMMC Evidence Pack", styles["PackTitle"]),
        Paragraph(f"Prepared by {consulting_name} for {client_name}", styles["Body"]),
        Spacer(1, 0.3 * cm),
        Paragraph(f"Exercise date: {_fmt_dt(payload['session']['exercise_date'])}", styles["Body"]),
        Paragraph("Controls addressed: NIST SP 800-171 3.6.3", styles["Body"]),
        Paragraph(f"Document ID: {payload['document_id']}", styles["Body"]),
        Spacer(1, 0.5 * cm),
        Paragraph(
            "This document is issued by BreachReplay for the exercise described below. "
            "It distinguishes what this exercise directly evidences from what the "
            "organization declares - see the Control Mapping section for a claim-by-claim account.",
            styles["Note"],
        ),
    ]
    return story


def _exercise_summary_section(payload: dict, styles) -> list:
    scenario = payload["scenario"]
    citation = scenario["source_reference"] or scenario["source_url"] or "-"
    story = [
        Paragraph("Exercise Summary", styles["SectionHeading"]),
        Paragraph(f"Scenario: {scenario['title']}", styles["Body"]),
        Paragraph(f"Source: {scenario['source_type']} - {citation}", styles["Body"]),
        Paragraph(f"Real-incident date: {_fmt_dt(scenario['incident_date'])}", styles["Body"]),
        Paragraph(f"Session title: {payload['session']['title']}", styles["Body"]),
        Spacer(1, 0.3 * cm),
    ]
    return story


def _participants_section(payload: dict, styles) -> list:
    rows = [["Participant", "Role", "Outcome"]]
    for p in payload["aggregate"]["participants"]:
        rows.append([p["participant_name"], "Client participant", p["outcome"]])
    story = [Paragraph("Participants", styles["SectionHeading"]), _table(rows, [7 * cm, 5 * cm, 5 * cm])]
    return story


def _timeline_section(payload: dict, styles) -> list:
    story = [Paragraph("Timeline", styles["SectionHeading"])]
    story.append(Paragraph(
        "This timeline reflects every logged action and the scenario's attacker-stage "
        "progression, reconstructed from recorded run data. The simulated tool output "
        "shown to each participant during play (e.g., specific command output, log "
        "excerpts) is not persisted and is not evidenced by this exercise.",
        styles["Note"],
    ))

    rows = [["Time (elapsed)", "Participant", "Action"]]
    for entry in payload["aggregate"]["timeline"]:
        target = f" -> {entry['target']}" if entry.get("target") else ""
        rows.append([
            f"{entry['elapsed_seconds_in_run']}s",
            entry["participant_name"],
            f"{entry['verb']}{target}",
        ])
    story.append(_table(rows, [3 * cm, 6 * cm, 8 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Attacker stage progression (per participant, recomputed from the scenario and run seed)", styles["Body"]))
    for run_stages in payload["attacker_stages"]:
        story.append(Paragraph(run_stages["participant_name"], styles["Body"]))
        stage_rows = [["Trigger (s)", "Kind", "MITRE", "Final", "Hosts compromised if uncontained"]]
        for stage in run_stages["stages"]:
            stage_rows.append([
                str(stage["trigger_seconds"]),
                stage["kind"],
                stage["mitre_technique"] or "-",
                "Yes" if stage["is_final"] else "No",
                ", ".join(stage["compromised_hostnames"]) or "-",
            ])
        story.append(_table(stage_rows, [2.5 * cm, 3 * cm, 3 * cm, 2 * cm, 6.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
    return story


def _outcomes_section(payload: dict, styles) -> list:
    story = [Paragraph("Outcomes", styles["SectionHeading"])]
    dist = payload["aggregate"]["outcome_distribution"]
    dist_str = ", ".join(f"{k}: {v}" for k, v in dist.items())
    story.append(Paragraph(f"Session summary (distribution across {payload['aggregate']['participant_count']} participant(s)): {dist_str}", styles["Body"]))
    story.append(Paragraph(
        "No single session-level outcome is computed - a team's exercise produces "
        "several independently graded outcomes; the distribution above is the complete answer.",
        styles["Note"],
    ))

    rows = [["Participant", "Outcome", "Score"]]
    for p in payload["aggregate"]["participants"]:
        rows.append([p["participant_name"], p["outcome"], f"{p['total_score']} ({p['score_pct']}%)"])
    story.append(_table(rows, [7 * cm, 6 * cm, 4 * cm]))
    return story


def _operational_impact_section(payload: dict, styles) -> list:
    story = [Paragraph("Operational Impact of the Response", styles["SectionHeading"])]
    story.append(Paragraph(
        f"Total avoidable collateral cost across the exercise: {payload['aggregate']['collateral_total_penalty']}.",
        styles["Body"],
    ))
    rows = [["Participant", "Host", "Weight"]]
    any_collateral = False
    for p in payload["aggregate"]["participants"]:
        for host in p["collateral"]:
            any_collateral = True
            rows.append([p["participant_name"], host.get("hostname", host.get("host_id", "-")), str(host.get("weight", "-"))])
    if any_collateral:
        story.append(_table(rows, [6 * cm, 6 * cm, 5 * cm]))
    else:
        story.append(Paragraph("No systems were taken offline unnecessarily during this exercise.", styles["Body"]))
    return story


def _evidence_discovered_section(payload: dict, styles) -> list:
    story = [Paragraph("Evidence Discovered", styles["SectionHeading"])]
    rows = [["Participant", "Indicators Found", "Indicators Total"]]
    for p in payload["aggregate"]["participants"]:
        rows.append([p["participant_name"], str(p["evidence_found"]), str(p["evidence_total"])])
    story.append(_table(rows, [7 * cm, 5 * cm, 5 * cm]))
    story.append(Paragraph(
        "The identities of specific indicators discovered or missed are not evidenced "
        "by this exercise; only aggregate counts are recorded.",
        styles["Note"],
    ))
    return story


def _notifications_section(payload: dict, styles) -> list:
    story = [Paragraph("Notifications", styles["SectionHeading"])]

    matrix = payload["notification_matrix"]
    story.append(Paragraph("Declared notification matrix", styles["Body"]))
    if matrix:
        rows = [["Authority", "Basis", "Channel", "Window"]]
        for entry in matrix:
            rows.append([entry["authority"], entry["basis"], entry["channel"], entry["window"]])
        story.append(_table(rows, [4 * cm, 5 * cm, 4 * cm, 4 * cm]))
    else:
        story.append(Paragraph("No notification matrix has been declared for this client org.", styles["Body"]))

    escalations = payload["aggregate"]["escalations"]
    n = len(escalations)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Escalations logged during this exercise", styles["Body"]))
    if n:
        rows = [["Participant", "Elapsed time from exercise start"]]
        for e in escalations:
            rows.append([e["participant_name"], f"{e['elapsed_seconds_in_run']}s"])
        story.append(_table(rows, [8 * cm, 9 * cm]))
        story.append(Paragraph(
            f"{n} escalation(s) occurred during this exercise (logged above: who, and elapsed "
            "time from exercise start). This exercise does not evidence which declared authority, "
            "channel, or obligation - if any - each escalation was directed to. The mapping "
            "between escalation events and the organization's declared notification matrix "
            "above is not evidenced by this exercise.",
            styles["Note"],
        ))
    else:
        story.append(Paragraph("No escalations were logged during this exercise.", styles["Body"]))
    return story


def _lessons_remediation_section(payload: dict, styles) -> list:
    story = [Paragraph("Lessons Learned and Remediation", styles["SectionHeading"])]

    story.append(Paragraph("Lessons learned", styles["Body"]))
    for lesson in payload["lessons_learned"]:
        anchor = lesson.get("anchor")
        anchor_str = ""
        if anchor:
            anchor_str = f" (anchored to {anchor['participant_name']}'s {anchor['verb']} at {anchor['elapsed_seconds']}s)"
        story.append(Paragraph(
            f"- {lesson['text']}{anchor_str} - {lesson['created_by_name']}, {_fmt_dt(lesson['created_at'])}",
            styles["Body"],
        ))
    if not payload["lessons_learned"]:
        story.append(Paragraph("No lessons were recorded for this exercise.", styles["Body"]))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Remediation items", styles["Body"]))
    items = payload["remediation_items"]
    if items:
        rows = [["Description", "Owner", "Due", "Status"]]
        for item in items:
            rows.append([item["description"], item["owner"], _fmt_dt(item["due_date"]), item["status"]])
        story.append(_table(rows, [7 * cm, 4 * cm, 4 * cm, 2 * cm]))
    else:
        story.append(Paragraph("No remediation items were recorded for this exercise.", styles["Body"]))
    return story


def _irp_linkage_section(payload: dict, styles) -> list:
    story = [Paragraph("IRP Linkage", styles["SectionHeading"])]
    story.append(Paragraph(f"IRP reference: {payload['irp_reference'] or 'not declared'}", styles["Body"]))
    rows = [["Lesson", "Incorporated", "Note"]]
    for lesson in payload["lessons_learned"]:
        rows.append([lesson["text"][:60], lesson.get("irp_incorporated") or "not assessed", lesson.get("irp_note") or "-"])
    if len(rows) > 1:
        story.append(_table(rows, [8 * cm, 3 * cm, 6 * cm]))
    else:
        story.append(Paragraph("No lessons to map against the IRP.", styles["Body"]))
    story.append(Paragraph(
        "IRP linkage is an attestation - recorded as declared by the organization, not independently verified.",
        styles["Note"],
    ))
    return story


def _control_mapping_section(payload: dict, styles) -> list:
    story = [Paragraph("Control Mapping", styles["SectionHeading"])]
    rows = [["Control", "Claim", "Evidenced", "Note"]]
    for row in payload["control_mapping"]:
        rows.append([row["control"], row["claim"], "Yes" if row["evidenced"] else "No", row["note"]])
    table = _table(rows, [2 * cm, 6 * cm, 2 * cm, 7 * cm])
    # Colour the Evidenced column per-row — setStyle calls accumulate on
    # top of _table()'s base style, they don't replace it.
    for i, row in enumerate(payload["control_mapping"], start=1):
        color = _GREEN if row["evidenced"] else _RED
        table.setStyle(TableStyle([("TEXTCOLOR", (2, i), (2, i), color), ("FONTNAME", (2, i), (2, i), "Helvetica-Bold")]))
    story.append(table)
    return story


def _attestation_section(payload: dict, styles) -> list:
    story = [Paragraph("Attestation and Signatures", styles["SectionHeading"])]
    client = payload["client_signoff"]
    consultant = payload["consultant_signoff"]
    story.append(Paragraph(
        f"Client attestation (record accuracy): {client['signed_by_name']}, {_fmt_dt(client['signed_at'])}",
        styles["Body"],
    ))
    story.append(Paragraph(
        f"Consultant attestation (facilitation): {consultant['signed_by_name']}, {_fmt_dt(consultant['signed_at'])}",
        styles["Body"],
    ))
    story.append(Paragraph(
        "This artifact was issued by BreachReplay for this session on this date. It does "
        "not itself claim the organization's declarations are true - see Control Mapping.",
        styles["Note"],
    ))
    return story


def generate_evidence_pack_pdf(payload: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
        title="CMMC Evidence Pack",
    )
    styles = _styles()

    story: list = []
    story += _cover_section(payload, styles)
    story.append(PageBreak())
    story += _exercise_summary_section(payload, styles)
    story += _participants_section(payload, styles)
    story.append(PageBreak())
    story += _timeline_section(payload, styles)
    story.append(PageBreak())
    story += _outcomes_section(payload, styles)
    story += _operational_impact_section(payload, styles)
    story.append(PageBreak())
    story += _evidence_discovered_section(payload, styles)
    story += _notifications_section(payload, styles)
    story.append(PageBreak())
    story += _lessons_remediation_section(payload, styles)
    story += _irp_linkage_section(payload, styles)
    story.append(PageBreak())
    story += _control_mapping_section(payload, styles)
    story += _attestation_section(payload, styles)

    doc.build(story)
    return buf.getvalue()
