"""Phase 2.5 CMMC Evidence Layer — evidence pack generation (build-order
item 6).

Rendering pipeline (pivoted from an initial reportlab version after visual
review — see git history / the plan doc for why): HTML, styled with
BreachReplay's actual established palette (reused verbatim from
app/services/email_service.py's _HTML_WRAPPER — #0f172a navy, #1e293b
card, #ef4444 red accent — not invented fresh for this feature), rendered
to PDF via a real browser engine (Playwright + Chromium) rather than
reportlab's flowable layout primitives. Real HTML tables wrap text within
a cell by default, which is what reportlab's plain-string Table cells did
not do — that was the actual cause of the overlapping/overflowing text
in the first version, not a styling choice.

`build_control_mapping`/`build_pack_payload` are pure data assembly,
untouched by this pivot — completely rendering-engine-agnostic.

Determinism (item 7 hashes this output): Chromium's page.pdf() embeds a
live /CreationDate and /ModDate by default, verified empirically to be
the ONLY source of non-determinism for identical input (diffed two runs
of identical content down to exactly those two fields). Both are pinned
to a fixed value via a pypdf post-processing pass in render_pdf_from_html
— verified to produce byte-identical SHA-256 output across repeated runs.
test_cmmc_evidence_pack.py's determinism test makes this permanent: a
future Chromium/Playwright/pypdf upgrade that reintroduces non-determinism
(a new metadata field, different font-subsetting order) fails CI
immediately instead of silently breaking item 7's hash verification.

Two deliberate honesty mechanisms, both reported and approved before item
6 was first written, unchanged by this rendering pivot:
- §8 Notifications renders the declared matrix and the escalation log as
  two SEPARATE tables, never joined — a merged table would visually imply
  a mapping the data doesn't support.
- §11 Control mapping is a real `evidenced` column, not prose — see
  build_control_mapping's docstring for the exact claims and why only
  control 3.6.3 is mapped in this build.
"""
from __future__ import annotations

import html as html_escape
import uuid
from datetime import datetime, timedelta
from io import BytesIO

from playwright.async_api import async_playwright
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.scenario import Scenario
from app.services import action_engine
from app.services.cmmc_evidence import build_evidence_session_aggregate, runs_with_participant_names

# Pinned rather than "now" — the whole point is that regenerating the same
# session's pack twice produces byte-identical output (see module docstring).
_FIXED_PDF_METADATA_DATE = "D:20260101000000+00'00'"


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

def _esc(value) -> str:
    """Every payload string reaches real browser-parsed HTML now (unlike
    reportlab's Paragraph, which never executed markup) — lesson text,
    remediation descriptions, participant/org names are all user-supplied
    content and MUST be escaped before going into the template. Never
    build a cell/paragraph string by f-string-ing raw payload values
    directly into the HTML below without going through this first."""
    if value is None:
        return ""
    return html_escape.escape(str(value))


def _fmt_dt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return _esc(value)
    return value.strftime("%B %d, %Y %H:%M UTC")


_CSS = """
  @page { size: A4; margin: 2.2cm 1.8cm; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0; color: #1e293b;
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    font-size: 10pt; line-height: 1.5;
  }
  /* Sections flow continuously — no forced page-break-before. A pack with
     little content (few participants, few lessons) should be short; only
     the cover gets its own page (a letterhead convention, not a space-
     filler). Real page breaks happen only where content actually runs
     out of room, driven by Chromium's normal layout, not by section
     count. break-inside: avoid keeps a table's header from being stranded
     alone at the bottom of a page, separated from its own rows. */
  section { padding-top: 10px; margin-top: 6px; border-top: 1px solid #e2e8f0; }
  section:first-child { padding-top: 0; margin-top: 0; border-top: none; }
  h1 { font-size: 14pt; color: #0f172a; margin: 0 0 8px; padding-left: 12px; border-left: 4px solid #ef4444; }
  p { margin: 0 0 6px; }
  .note {
    font-size: 8.5pt; color: #64748b; font-style: italic;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px;
    padding: 6px 10px; margin: 6px 0 10px;
  }
  /* No break-inside:avoid on the table itself — a long timeline/lessons
     table should be allowed to split across pages between rows (its
     default behaviour, with <thead> repeating on each page) rather than
     being forced entirely onto its own page and wasting the space above
     it. Only individual rows are kept intact. */
  table { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 4px 0 10px; }
  tr { break-inside: avoid; page-break-inside: avoid; }
  th, td {
    border: 1px solid #e2e8f0; padding: 4px 8px; font-size: 8.5pt;
    text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word;
  }
  th { background: #1e293b; color: #f1f5f9; font-weight: 700; }
  tr:nth-child(even) td { background: #f8fafc; }
  .evidenced-yes { color: #15803d; font-weight: 700; }
  .evidenced-no { color: #b91c1c; font-weight: 700; }
  .cover {
    page-break-before: avoid; page-break-after: always;
    background: #0f172a; color: #f1f5f9; margin: -2.2cm -1.8cm; padding: 4cm 3cm;
    min-height: 100vh;
  }
  .cover .logo { font-size: 11pt; font-weight: 900; letter-spacing: 0.2em; color: #ef4444; text-transform: uppercase; margin-bottom: 24px; }
  .cover h1 { border: none; padding: 0; color: #f1f5f9; font-size: 26pt; margin: 0 0 10px; }
  .cover .subtitle { color: #cbd5e1; font-size: 12pt; margin-bottom: 28px; }
  .cover .meta-row { color: #cbd5e1; font-size: 10pt; margin-bottom: 6px; }
  .cover .meta-row b { color: #f1f5f9; }
  .cover .cover-note {
    margin-top: 32px; font-size: 9pt; color: #94a3b8; line-height: 1.6;
    border-top: 1px solid #334155; padding-top: 16px;
  }
  .subheading { font-size: 10.5pt; font-weight: 700; color: #0f172a; margin: 14px 0 6px; }
  .download-bar {
    background: #1e293b; padding: 14px 20px; text-align: center;
    position: sticky; top: 0; z-index: 10;
  }
  .download-bar a {
    display: inline-block; background: #ef4444; color: #fff; text-decoration: none;
    font-weight: 700; font-size: 11pt; padding: 10px 24px; border-radius: 6px;
    letter-spacing: 0.02em;
  }
  @media print { .no-print { display: none !important; } }
"""


def _cover_html(payload: dict) -> str:
    consulting_name = _esc(payload["consulting_org"]["name"])
    client_name = _esc(payload["client_org"]["name"])
    return f"""
<section class="cover">
  <div class="logo">&#11043; BreachReplay</div>
  <h1>CMMC Evidence Pack</h1>
  <div class="subtitle">Prepared by {consulting_name} for {client_name}</div>
  <div class="meta-row"><b>Exercise date:</b> {_esc(_fmt_dt(payload['session']['exercise_date']))}</div>
  <div class="meta-row"><b>Controls addressed:</b> NIST SP 800-171 3.6.3</div>
  <div class="meta-row"><b>Document ID:</b> {_esc(payload['document_id'])}</div>
  <div class="cover-note">
    This document is issued by BreachReplay for the exercise described within. It distinguishes
    what this exercise directly evidences from what the organization declares — see the Control
    Mapping section for a claim-by-claim account.
  </div>
</section>
"""


def _exercise_summary_html(payload: dict) -> str:
    scenario = payload["scenario"]
    citation = _esc(scenario["source_reference"] or scenario["source_url"] or "-")
    return f"""
<section>
  <h1>Exercise Summary</h1>
  <p><b>Scenario:</b> {_esc(scenario['title'])}</p>
  <p><b>Source:</b> {_esc(scenario['source_type'])} - {citation}</p>
  <p><b>Real-incident date:</b> {_esc(_fmt_dt(scenario['incident_date']))}</p>
  <p><b>Session title:</b> {_esc(payload['session']['title'])}</p>
  {_participants_html(payload)}
</section>
"""


def _participants_html(payload: dict) -> str:
    rows = "".join(
        f"<tr><td>{_esc(p['participant_name'])}</td><td>Client participant</td><td>{_esc(p['outcome'])}</td></tr>"
        for p in payload["aggregate"]["participants"]
    )
    return f"""
  <div class="subheading">Participants</div>
  <table>
    <colgroup><col style="width:40%"><col style="width:30%"><col style="width:30%"></colgroup>
    <thead><tr><th>Participant</th><th>Role</th><th>Outcome</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""


def _timeline_html(payload: dict) -> str:
    timeline_rows = "".join(
        f"<tr><td>{entry['elapsed_seconds_in_run']}s</td><td>{_esc(entry['participant_name'])}</td>"
        f"<td>{_esc(entry['verb'])}{' &rarr; ' + _esc(entry['target']) if entry.get('target') else ''}</td></tr>"
        for entry in payload["aggregate"]["timeline"]
    )
    stage_blocks = []
    for run_stages in payload["attacker_stages"]:
        stage_rows = "".join(
            f"<tr><td>{stage['trigger_seconds']}</td><td>{_esc(stage['kind'])}</td>"
            f"<td>{_esc(stage['mitre_technique'] or '-')}</td><td>{'Yes' if stage['is_final'] else 'No'}</td>"
            f"<td>{_esc(', '.join(stage['compromised_hostnames']) or '-')}</td></tr>"
            for stage in run_stages["stages"]
        )
        stage_blocks.append(f"""
  <p><i>{_esc(run_stages['participant_name'])}</i></p>
  <table>
    <colgroup><col style="width:14%"><col style="width:18%"><col style="width:16%"><col style="width:12%"><col style="width:40%"></colgroup>
    <thead><tr><th>Trigger (s)</th><th>Kind</th><th>MITRE</th><th>Final</th><th>Hosts compromised if uncontained</th></tr></thead>
    <tbody>{stage_rows}</tbody>
  </table>
""")
    return f"""
<section>
  <h1>Timeline</h1>
  <div class="note">
    This timeline reflects every logged action and the scenario's attacker-stage progression,
    reconstructed from recorded run data. The simulated tool output shown to each participant
    during play (e.g., specific command output, log excerpts) is not persisted and is not
    evidenced by this exercise.
  </div>
  <table>
    <colgroup><col style="width:18%"><col style="width:32%"><col style="width:50%"></colgroup>
    <thead><tr><th>Time (elapsed)</th><th>Participant</th><th>Action</th></tr></thead>
    <tbody>{timeline_rows}</tbody>
  </table>
  <div class="subheading">Attacker stage progression (per participant, recomputed from the scenario and run seed)</div>
  {''.join(stage_blocks)}
</section>
"""


def _outcomes_html(payload: dict) -> str:
    dist = payload["aggregate"]["outcome_distribution"]
    dist_str = ", ".join(f"{_esc(k)}: {v}" for k, v in dist.items())
    rows = "".join(
        f"<tr><td>{_esc(p['participant_name'])}</td><td>{_esc(p['outcome'])}</td>"
        f"<td>{p['total_score']} ({p['score_pct']}%)</td></tr>"
        for p in payload["aggregate"]["participants"]
    )
    return f"""
<section>
  <h1>Outcomes</h1>
  <p>Session summary (distribution across {payload['aggregate']['participant_count']} participant(s)): {dist_str}</p>
  <div class="note">
    No single session-level outcome is computed - a team's exercise produces several
    independently graded outcomes; the distribution above is the complete answer.
  </div>
  <table>
    <colgroup><col style="width:40%"><col style="width:30%"><col style="width:30%"></colgroup>
    <thead><tr><th>Participant</th><th>Outcome</th><th>Score</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {_operational_impact_html(payload)}
</section>
"""


def _operational_impact_html(payload: dict) -> str:
    rows = []
    for p in payload["aggregate"]["participants"]:
        for host in p["collateral"]:
            rows.append(
                f"<tr><td>{_esc(p['participant_name'])}</td>"
                f"<td>{_esc(host.get('hostname', host.get('host_id', '-')))}</td>"
                f"<td>{_esc(host.get('weight', '-'))}</td></tr>"
            )
    body = "".join(rows) if rows else '<tr><td colspan="3">No systems were taken offline unnecessarily during this exercise.</td></tr>'
    return f"""
  <div class="subheading">Operational Impact of the Response</div>
  <p>Total avoidable collateral cost across the exercise: {payload['aggregate']['collateral_total_penalty']}.</p>
  <table>
    <colgroup><col style="width:35%"><col style="width:35%"><col style="width:30%"></colgroup>
    <thead><tr><th>Participant</th><th>Host</th><th>Weight</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
"""


def _evidence_discovered_html(payload: dict) -> str:
    rows = "".join(
        f"<tr><td>{_esc(p['participant_name'])}</td><td>{p['evidence_found']}</td><td>{p['evidence_total']}</td></tr>"
        for p in payload["aggregate"]["participants"]
    )
    return f"""
<section>
  <h1>Evidence Discovered</h1>
  <table>
    <colgroup><col style="width:40%"><col style="width:30%"><col style="width:30%"></colgroup>
    <thead><tr><th>Participant</th><th>Indicators Found</th><th>Indicators Total</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="note">
    The identities of specific indicators discovered or missed are not evidenced by this
    exercise; only aggregate counts are recorded.
  </div>
  {_notifications_html(payload)}
</section>
"""


def _notifications_html(payload: dict) -> str:
    matrix = payload["notification_matrix"]
    if matrix:
        matrix_rows = "".join(
            f"<tr><td>{_esc(e['authority'])}</td><td>{_esc(e['basis'])}</td>"
            f"<td>{_esc(e['channel'])}</td><td>{_esc(e['window'])}</td></tr>"
            for e in matrix
        )
        matrix_html = f"""
  <table>
    <colgroup><col style="width:25%"><col style="width:30%"><col style="width:25%"><col style="width:20%"></colgroup>
    <thead><tr><th>Authority</th><th>Basis</th><th>Channel</th><th>Window</th></tr></thead>
    <tbody>{matrix_rows}</tbody>
  </table>
"""
    else:
        matrix_html = "<p>No notification matrix has been declared for this client org.</p>"

    escalations = payload["aggregate"]["escalations"]
    n = len(escalations)
    if n:
        esc_rows = "".join(
            f"<tr><td>{_esc(e['participant_name'])}</td><td>{e['elapsed_seconds_in_run']}s</td></tr>"
            for e in escalations
        )
        esc_html = f"""
  <table>
    <colgroup><col style="width:50%"><col style="width:50%"></colgroup>
    <thead><tr><th>Participant</th><th>Elapsed time from exercise start</th></tr></thead>
    <tbody>{esc_rows}</tbody>
  </table>
  <div class="note">
    {n} escalation(s) occurred during this exercise (logged above: who, and elapsed time from
    exercise start). This exercise does not evidence which declared authority, channel, or
    obligation - if any - each escalation was directed to. The mapping between escalation
    events and the organization's declared notification matrix above is not evidenced by
    this exercise.
  </div>
"""
    else:
        esc_html = "<p>No escalations were logged during this exercise.</p>"

    return f"""
  <div class="subheading">Notifications</div>
  <p>Declared notification matrix</p>
  {matrix_html}
  <p>Escalations logged during this exercise</p>
  {esc_html}
"""


def _lessons_remediation_html(payload: dict) -> str:
    lessons = payload["lessons_learned"]
    if lessons:
        lesson_items = []
        for lesson in lessons:
            anchor = lesson.get("anchor")
            anchor_str = ""
            if anchor:
                anchor_str = (
                    f" <i>(anchored to {_esc(anchor['participant_name'])}'s "
                    f"{_esc(anchor['verb'])} at {anchor['elapsed_seconds']}s)</i>"
                )
            lesson_items.append(
                f"<li>{_esc(lesson['text'])}{anchor_str}<br>"
                f"<span style=\"color:#64748b;font-size:8.5pt;\">"
                f"{_esc(lesson['created_by_name'])}, {_esc(_fmt_dt(lesson['created_at']))}</span></li>"
            )
        lessons_html = f"<ul style=\"padding-left:18px;\">{''.join(lesson_items)}</ul>"
    else:
        lessons_html = "<p>No lessons were recorded for this exercise.</p>"

    items = payload["remediation_items"]
    if items:
        item_rows = "".join(
            f"<tr><td>{_esc(item['description'])}</td><td>{_esc(item['owner'])}</td>"
            f"<td>{_esc(_fmt_dt(item['due_date']))}</td><td>{_esc(item['status'])}</td></tr>"
            for item in items
        )
        items_html = f"""
  <table>
    <colgroup><col style="width:45%"><col style="width:20%"><col style="width:20%"><col style="width:15%"></colgroup>
    <thead><tr><th>Description</th><th>Owner</th><th>Due</th><th>Status</th></tr></thead>
    <tbody>{item_rows}</tbody>
  </table>
"""
    else:
        items_html = "<p>No remediation items were recorded for this exercise.</p>"

    return f"""
<section>
  <h1>Lessons Learned and Remediation</h1>
  <div class="subheading">Lessons learned</div>
  {lessons_html}
  <div class="subheading">Remediation items</div>
  {items_html}
  {_irp_linkage_html(payload)}
</section>
"""


def _irp_linkage_html(payload: dict) -> str:
    lessons = payload["lessons_learned"]
    if lessons:
        rows = "".join(
            f"<tr><td>{_esc(lesson['text'])}</td><td>{_esc(lesson.get('irp_incorporated') or 'not assessed')}</td>"
            f"<td>{_esc(lesson.get('irp_note') or '-')}</td></tr>"
            for lesson in lessons
        )
        table_html = f"""
  <table>
    <colgroup><col style="width:50%"><col style="width:20%"><col style="width:30%"></colgroup>
    <thead><tr><th>Lesson</th><th>Incorporated</th><th>Note</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""
    else:
        table_html = "<p>No lessons to map against the IRP.</p>"

    return f"""
  <div class="subheading">IRP Linkage</div>
  <p>IRP reference: {_esc(payload['irp_reference'] or 'not declared')}</p>
  {table_html}
  <div class="note">
    IRP linkage is an attestation - recorded as declared by the organization, not
    independently verified.
  </div>
"""


def _control_mapping_html(payload: dict) -> str:
    rows = "".join(
        f"<tr><td>{_esc(row['control'])}</td><td>{_esc(row['claim'])}</td>"
        f"<td class=\"{'evidenced-yes' if row['evidenced'] else 'evidenced-no'}\">"
        f"{'Yes' if row['evidenced'] else 'No'}</td><td>{_esc(row['note'])}</td></tr>"
        for row in payload["control_mapping"]
    )
    return f"""
<section>
  <h1>Control Mapping</h1>
  <table>
    <colgroup><col style="width:10%"><col style="width:38%"><col style="width:12%"><col style="width:40%"></colgroup>
    <thead><tr><th>Control</th><th>Claim</th><th>Evidenced</th><th>Note</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {_attestation_html(payload)}
</section>
"""


def _attestation_html(payload: dict) -> str:
    client = payload["client_signoff"]
    consultant = payload["consultant_signoff"]
    return f"""
  <div class="subheading">Attestation and Signatures</div>
  <p><b>Client attestation (record accuracy):</b> {_esc(client['signed_by_name'])}, {_esc(_fmt_dt(client['signed_at']))}</p>
  <p><b>Consultant attestation (facilitation):</b> {_esc(consultant['signed_by_name'])}, {_esc(_fmt_dt(consultant['signed_at']))}</p>
  <div class="note">
    This artifact was issued by BreachReplay for this session on this date. It does not
    itself claim the organization's declarations are true - see Control Mapping.
  </div>
"""


def render_evidence_pack_html(payload: dict, *, show_download_button: bool = False) -> str:
    """The same 12 sections/wording as item 6's original reportlab version,
    as HTML. `show_download_button` is only True for the human-facing
    /pack/view route — the PDF-rendering path never wants that button in
    the printed output (the .no-print CSS rule would hide it in print
    media anyway, but omitting it outright keeps the PDF's HTML source
    minimal and avoids depending on emulate_media doing the right thing)."""
    download_bar = ""
    if show_download_button:
        download_bar = f"""
<div class="download-bar no-print">
  <a href="/api/v1/cmmc/evidence-sessions/{payload['aggregate']['evidence_session_id']}/pack">Download PDF</a>
</div>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CMMC Evidence Pack</title>
<style>{_CSS}</style>
</head>
<body>
{download_bar}
{_cover_html(payload)}
{_exercise_summary_html(payload)}
{_timeline_html(payload)}
{_outcomes_html(payload)}
{_evidence_discovered_html(payload)}
{_lessons_remediation_html(payload)}
{_control_mapping_html(payload)}
</body>
</html>
"""


_DEFAULT_FOOTER_TEMPLATE = (
    '<div style="width:100%;font-size:7.5pt;color:#94a3b8;'
    'text-align:center;font-family:Arial,sans-serif;">'
    "BreachReplay CMMC Evidence Pack &middot; "
    '<span class="pageNumber"></span> / <span class="totalPages"></span>'
    "</div>"
)


async def render_pdf_from_html(html: str, *, footer_template: str = _DEFAULT_FOOTER_TEMPLATE) -> bytes:
    """Playwright's ASYNC api, never the sync one — docker-compose.prod.yml
    runs the backend with --workers 1 (Live Arena's in-process singleton
    state requires it), so a blocking sync call during a ~1-3s render
    would stall the entire app for every other user, not just the
    requester. A fresh browser per request, not a kept-warm pool — this
    is a low-frequency route; pooling is a legitimate future optimization
    if pack-generation volume ever justifies the added lifecycle
    complexity, not built now.

    The pypdf pass at the end is not cleanup — it's the fix for the one
    verified source of non-determinism (Chromium's live /CreationDate and
    /ModDate), pinned to a fixed value so identical session data always
    produces byte-identical output. See module docstring."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            await page.emulate_media(media="print")
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=footer_template,
                margin={"top": "2.2cm", "bottom": "1.6cm", "left": "1.8cm", "right": "1.8cm"},
            )
        finally:
            await browser.close()

    return _pin_pdf_metadata(pdf_bytes)


def _pin_pdf_metadata(pdf_bytes: bytes) -> bytes:
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_metadata({
        "/CreationDate": _FIXED_PDF_METADATA_DATE,
        "/ModDate": _FIXED_PDF_METADATA_DATE,
        "/Producer": "BreachReplay",
    })
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


async def generate_evidence_pack_pdf(payload: dict) -> bytes:
    html = render_evidence_pack_html(payload, show_download_button=False)
    return await render_pdf_from_html(html)


def _certifiable_footer_template(document_id: str, verify_url: str) -> str:
    return (
        '<div style="width:100%;font-size:7pt;color:#94a3b8;'
        'text-align:center;font-family:Arial,sans-serif;padding:0 1.8cm;">'
        f"BreachReplay CMMC Evidence Pack &middot; Document ID: {_esc(document_id)} "
        f"&middot; Verify at: {_esc(verify_url)} &middot; "
        '<span class="pageNumber"></span> / <span class="totalPages"></span>'
        "</div>"
    )


async def render_certifiable_pdf(payload: dict, *, document_id: str, verify_url: str) -> bytes:
    """The exact bytes that get hashed and signed at issuance (build-order
    item 7). Same 12 sections/wording as render_evidence_pack_html — only
    the footer differs, carrying the Document ID and verification URL
    (both knowable before hashing) but deliberately NOT the hash or
    signature themselves.

    This isn't a style choice: a hash cannot include a printed copy of
    its own output (H = SHA256(bytes containing "the hash is H") is
    circular for any hash function). The one real technique that could
    work around this — hash with a fixed-length placeholder, then
    byte-patch the real digest in afterward — is fragile against
    Chromium's compressed PDF content streams, so it wasn't built.
    Reported and accepted before this was written: an assessor gets the
    hash/signature by visiting the verification URL printed here, not by
    reading raw hex off the page."""
    html = render_evidence_pack_html(payload, show_download_button=False)
    footer = _certifiable_footer_template(document_id, verify_url)
    return await render_pdf_from_html(html, footer_template=footer)
