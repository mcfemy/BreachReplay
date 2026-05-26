import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from app.models.session import SimulationSession


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute total pages and draw headers/footers
    with page numbers on every page.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#64748B'))

        # Header (pages after Cover page)
        if self._pageNumber > 1:
            self.drawString(54, 750, "BreachReplay — SOC Tabletop Simulation Audit Report")
            self.setStrokeColor(colors.HexColor('#CBD5E1'))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor('#CBD5E1'))
        self.setLineWidth(0.5)
        self.line(54, 50, 558, 50)

        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 38, page_text)
        self.drawString(54, 38, "CONFIDENTIAL — Cybersecurity Training tabletop Records")
        self.restoreState()


def generate_debrief_pdf(session: SimulationSession, debrief_report: dict) -> bytes:
    """
    Generates a professional tabletop exercise debrief PDF report from session data
    and its Claude-extracted debrief report dict. Returns the raw PDF bytes.
    """
    bio = io.BytesIO()

    # Page Margins setup
    doc = SimpleDocTemplate(
        bio,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )

    styles = getSampleStyleSheet()

    # Custom styles palette (Tailwind-aligned Navy / Charcoal theme)
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=10
    )
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#475569'),
        spaceAfter=25
    )
    heading1_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=18,
        spaceAfter=8,
        keepWithNext=True
    )
    heading2_style = ParagraphStyle(
        'SubSectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#B91C1C'),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )
    italic_body_style = ParagraphStyle(
        'ItalicBodyTextCustom',
        parent=body_style,
        fontName='Helvetica-Oblique'
    )
    bold_body_style = ParagraphStyle(
        'BoldBodyTextCustom',
        parent=body_style,
        fontName='Helvetica-Bold'
    )

    # Table cell formats
    table_cell_style = ParagraphStyle(
        'TableCellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#334155')
    )
    table_cell_bold = ParagraphStyle(
        'TableCellTextBold',
        parent=table_cell_style,
        fontName='Helvetica-Bold'
    )
    table_cell_header = ParagraphStyle(
        'TableCellTextHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white
    )

    story = []

    # --- COVER SECTION ---
    story.append(Paragraph("BREACH REPLAY", ParagraphStyle('AppLogo', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#EF4444'), spaceAfter=15)))
    story.append(Paragraph("Tabletop Simulation Debrief Report", title_style))
    story.append(Paragraph(f"Official Training Evidence Package • Incident Audit Log", subtitle_style))

    # Meta-information Metadata box
    session_date = session.completed_at.strftime("%Y-%m-%d %H:%M UTC") if session.completed_at else datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    meta_data = [
        [Paragraph("Simulation Session ID", table_cell_bold), Paragraph(str(session.id), table_cell_style)],
        [Paragraph("Scenario Title", table_cell_bold), Paragraph(session.scenario.title if session.scenario else "N/A", table_cell_style)],
        [Paragraph("Completion Date", table_cell_bold), Paragraph(session_date, table_cell_style)],
        [Paragraph("Session Mode", table_cell_bold), Paragraph(session.mode.upper(), table_cell_style)],
        [Paragraph("Incident Commander", table_cell_bold), Paragraph("Authenticated SOC Analyst", table_cell_style)],
    ]
    meta_table = Table(meta_data, colWidths=[150, 354])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#F1F5F9')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # Score Card Widget block
    score = session.team_score if session.team_score is not None else 0
    rating = debrief_report.get("performance_rating", "needs_improvement")
    rating_color = '#10B981' if rating == 'excellent' else ('#3B82F6' if rating == 'good' else ('#F59E0B' if rating == 'needs_improvement' else '#EF4444'))
    
    score_data = [
        [
            Paragraph("NIST compliance Score", table_cell_header),
            Paragraph("Training Evaluation", table_cell_header),
            Paragraph("Decisions Audited", table_cell_header),
        ],
        [
            Paragraph(f"<font size=24 color='#10B981'><b>{score}%</b></font>", styles['Normal']),
            Paragraph(f"<font size=12 color='{rating_color}'><b>{rating.upper().replace('_', ' ')}</b></font>", styles['Normal']),
            Paragraph(f"<font size=12 color='#334155'><b>{session.decisions_correct} / {session.decisions_made} Correct</b></font>", styles['Normal']),
        ]
    ]
    score_table = Table(score_data, colWidths=[168, 168, 168])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 15))

    # Executive Summary Paragraph
    story.append(Paragraph("Executive Summary", heading1_style))
    exec_summary = debrief_report.get("executive_summary", "Claude AI has compiled details on your tabletop replay...")
    story.append(Paragraph(exec_summary, body_style))
    story.append(Spacer(1, 10))

    # Force page break so decisions log goes neatly onto Page 2
    story.append(PageBreak())

    # --- INTERACTIVE DECISION AUDIT LOG ---
    story.append(Paragraph("Interactive Decision Audit Log", heading1_style))
    story.append(Paragraph("A chronological breakdown of all incident response decisions made by the team during this simulation session:", body_style))
    story.append(Spacer(1, 8))

    decisions = debrief_report.get("decisions", [])
    if decisions:
        for idx, dec in enumerate(decisions):
            gate_id = dec.get("gate_id", f"Gate {idx+1}")
            is_correct = dec.get("is_correct", False)
            verdict = "<font color='#10B981'><b>CORRECT ✓</b></font>" if is_correct else "<font color='#EF4444'><b>WRONG ✗</b></font>"
            
            dec_meta = [
                [
                    Paragraph(f"<b>Gate ID:</b> {gate_id}", table_cell_bold),
                    Paragraph(f"<b>NIST Reference:</b> {dec.get('nist_ref', 'N/A')}", table_cell_style),
                    Paragraph(f"<b>Result:</b> {verdict}", table_cell_style),
                ]
            ]
            dec_meta_table = Table(dec_meta, colWidths=[150, 150, 204])
            dec_meta_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ('PADDING', (0, 0), (-1, -1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            dec_details = [
                [Paragraph("Action Taken", table_cell_bold), Paragraph(dec.get("team_choice", "N/A"), table_cell_style)],
                [Paragraph("Recommended Protocol", table_cell_bold), Paragraph(dec.get("correct_choice", "N/A"), table_cell_style)],
                [Paragraph("Downstream Impact", table_cell_bold), Paragraph(dec.get("impact", "N/A"), table_cell_style)],
                [Paragraph("Protocol Rationale", table_cell_bold), Paragraph(dec.get("explanation", "N/A"), italic_body_style)],
            ]
            dec_details_table = Table(dec_details, colWidths=[120, 384])
            dec_details_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('PADDING', (0, 0), (-1, -1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            
            # Keep each decision block together on a single page
            story.append(KeepTogether([
                dec_meta_table,
                dec_details_table,
                Spacer(1, 10)
            ]))
    else:
        story.append(Paragraph("No decisions recorded for this simulation session.", italic_body_style))

    story.append(Spacer(1, 10))
    story.append(PageBreak())

    # --- COMPLIANCE & FRAMEWORKS SECTION ---
    story.append(Paragraph("Framework Coverages & Control Gaps", heading1_style))
    story.append(Spacer(1, 5))

    # NIST SP 800-61 Control Gaps
    story.append(Paragraph("NIST SP 800-61 Rev 2 Control Gaps", heading2_style))
    nist_gaps = debrief_report.get("nist_gaps", [])
    if nist_gaps:
        gap_table_data = [
            [
                Paragraph("Control", table_cell_header),
                Paragraph("Identified Security Gap", table_cell_header),
                Paragraph("Remediation Plan", table_cell_header)
            ]
        ]
        for gap in nist_gaps:
            gap_table_data.append([
                Paragraph(f"<b>{gap.get('control', 'N/A')}</b><br/><font size=7 color='#64748B'>{gap.get('description', '')}</font>", table_cell_style),
                Paragraph(gap.get("gap", "N/A"), table_cell_style),
                Paragraph(gap.get("remediation", "N/A"), table_cell_style)
            ])
        gap_table = Table(gap_table_data, colWidths=[100, 204, 200])
        gap_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(gap_table)
    else:
        story.append(Paragraph("✓ Perfect Compliance: Zero critical NIST Control Gaps identified during this tabletop exercise.", ParagraphStyle('SuccessText', parent=body_style, textColor=colors.HexColor('#10B981'))))

    story.append(Spacer(1, 10))

    # MITRE ATT&CK Mapping
    story.append(Paragraph("MITRE ATT&CK Mapping", heading2_style))
    mitre_cov = debrief_report.get("mitre_coverage", {})
    exercised = ", ".join(mitre_cov.get("techniques_exercised", [])) or "None"
    missed = ", ".join(mitre_cov.get("techniques_missed", [])) or "None"
    
    mitre_data = [
        [Paragraph("Techniques Exercised", table_cell_bold), Paragraph(exercised, table_cell_style)],
        [Paragraph("Techniques Missed / Undetected", table_cell_bold), Paragraph(missed, table_cell_style)],
    ]
    mitre_table = Table(mitre_data, colWidths=[130, 374])
    mitre_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    story.append(mitre_table)

    story.append(Spacer(1, 15))

    # --- AUDIT COMPLIANCE & CHECKLIST SIGN-OFF ---
    story.append(Paragraph("Compliance Evidence Package", heading1_style))
    compliance = debrief_report.get("compliance_evidence", {})
    audit_notes = compliance.get("audit_notes", "This tabletop simulation training satisfies cybersecurity readiness tabletop exercise parameters.")
    frameworks = compliance.get("frameworks_exercised") or ["NIST SP 800-61"]
    story.append(Paragraph(f"<b>Frameworks Exercised:</b> {', '.join(frameworks)}", body_style))
    story.append(Paragraph(f"<b>Audit Notes:</b> {audit_notes}", italic_body_style))

    story.append(Spacer(1, 10))

    # Action Item Checklist
    story.append(Paragraph("Remediation Action Item Checklist", heading2_style))
    checklist = debrief_report.get("remediation_checklist", [])
    if checklist:
        chk_data = [
            [
                Paragraph("Priority", table_cell_header),
                Paragraph("Remediation Action Item", table_cell_header),
                Paragraph("Owner Role", table_cell_header),
                Paragraph("Due", table_cell_header)
            ]
        ]
        for item in checklist:
            priority = item.get("priority", "medium").upper()
            p_color = '#EF4444' if priority == 'HIGH' else ('#F59E0B' if priority == 'MEDIUM' else '#3B82F6')
            chk_data.append([
                Paragraph(f"<font color='{p_color}'><b>{priority}</b></font>", table_cell_style),
                Paragraph(item.get("action", "N/A"), table_cell_style),
                Paragraph(item.get("owner", "N/A"), table_cell_style),
                Paragraph(f"{item.get('due_days', 30)} Days", table_cell_style),
            ])
        chk_table = Table(chk_data, colWidths=[70, 264, 110, 60])
        chk_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(chk_table)

    story.append(Spacer(1, 15))

    # Sign-off block
    story.append(Paragraph("<b>Tabletop Training Sign-Off</b>", bold_body_style))
    story.append(Spacer(1, 5))
    sign_off_data = [
        [Paragraph("Authorized CISO / Administrator Signature:", table_cell_bold), Paragraph("___________________________", table_cell_style), Paragraph("Date: ______________", table_cell_style)],
        [Paragraph("Incident Commander Signature:", table_cell_bold), Paragraph("___________________________", table_cell_style), Paragraph("Date: ______________", table_cell_style)]
    ]
    sign_off_table = Table(sign_off_data, colWidths=[200, 180, 124])
    sign_off_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(sign_off_table)

    # Build the document
    doc.build(story, canvasmaker=NumberedCanvas)

    bio.seek(0)
    return bio.getvalue()
