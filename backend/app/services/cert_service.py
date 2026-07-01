"""
Certification Service.
Checks eligibility for verifiable credentials and issues them when earned.
"""
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.logging import get_logger
from app.services import mastery_service

logger = get_logger(__name__)

# ── Certification catalogue ────────────────────────────────────────────────────

CERTIFICATIONS = {
    "ir_fundamentals": {
        "title": "Incident Response Fundamentals",
        "subtitle": "Verified Completion · BreachReplay",
        "tier": "bronze",
        "color": "#cd7f32",
        "icon": "🛡️",
        "desc": "Demonstrated foundational skills in incident response by completing multiple cybersecurity scenarios.",
        "criteria_display": "Complete 3 scenarios with 60%+ avg score",
    },
    "certified_analyst": {
        "title": "BreachReplay Certified Analyst",
        "subtitle": "Career Progression · BreachReplay",
        "tier": "bronze",
        "color": "#cd7f32",
        "icon": "🔬",
        "desc": "Achieved SOC Analyst career tier through consistent training and skill development.",
        "criteria_display": "Reach SOC Analyst career tier (1,000 XP)",
    },
    "red_team_operator": {
        "title": "Red Team Operator Level I",
        "subtitle": "Offensive Security · BreachReplay",
        "tier": "bronze",
        "color": "#cd7f32",
        "icon": "🔴",
        "desc": "Demonstrated proficiency in adversarial simulation by completing multiple Red Team operations.",
        "criteria_display": "Complete 2 Red Team operations",
    },
    "ransomware_defender": {
        "title": "Ransomware Defense Specialist",
        "subtitle": "Threat-Specific Mastery · BreachReplay",
        "tier": "silver",
        "color": "#c0c0c0",
        "icon": "💊",
        "desc": "Proven expertise in ransomware incident response and containment strategies.",
        "criteria_display": "Complete 2 ransomware scenarios with 65%+ score",
    },
    "daily_champion": {
        "title": "Daily Breach Champion",
        "subtitle": "Consistency Award · BreachReplay",
        "tier": "silver",
        "color": "#c0c0c0",
        "icon": "🔥",
        "desc": "Demonstrated commitment to continuous learning with an exceptional Daily Breach streak.",
        "criteria_display": "7-day Daily Breach streak",
    },
    "critical_infra_defender": {
        "title": "Critical Infrastructure Defender",
        "subtitle": "Scenario Mastery · BreachReplay",
        "tier": "gold",
        "color": "#ffd700",
        "icon": "🛢️",
        "desc": "Successfully navigated the Colonial Pipeline scenario, demonstrating expertise in critical infrastructure protection.",
        "criteria_display": "Complete the Colonial Pipeline scenario",
    },
    "supply_chain_expert": {
        "title": "Supply Chain Security Expert",
        "subtitle": "Scenario Mastery · BreachReplay",
        "tier": "gold",
        "color": "#ffd700",
        "icon": "🌐",
        "desc": "Proven mastery of supply chain attack vectors through completion of the SolarWinds scenario.",
        "criteria_display": "Complete the SolarWinds scenario",
    },
    "elite_operator": {
        "title": "Elite Threat Hunter",
        "subtitle": "Advanced Career · BreachReplay",
        "tier": "platinum",
        "color": "#e5e4e2",
        "icon": "🎖️",
        "desc": "Reached the Threat Hunter career tier — placing this analyst in the top tier of BreachReplay practitioners.",
        "criteria_display": "Reach Threat Hunter career tier (15,000 XP)",
    },
}


async def _average_mastery_pct(db: AsyncSession, user_id: str) -> float | None:
    """
    Average accuracy_pct across all techniques tracked in compute_user_mastery.
    Returns None if the user has zero tracked techniques (nothing to average).
    """
    mastery = await mastery_service.compute_user_mastery(db, user_id)
    if not mastery:
        return None
    total = sum(entry["accuracy_pct"] for entry in mastery.values())
    return round(total / len(mastery), 1)


async def _meets_mastery_threshold(db: AsyncSession, user_id: str, min_accuracy_pct: float = 70) -> bool:
    """
    True if the user's average technique-mastery accuracy (across all techniques
    they've touched) is >= min_accuracy_pct. A user with zero tracked techniques has
    nothing to be confident about, so this returns False, not True, for them.
    """
    avg = await _average_mastery_pct(db, user_id)
    if avg is None:
        return False
    return avg >= min_accuracy_pct


async def _is_first_attempt_for_scenario(db: AsyncSession, user_id: str, scenario_id: str, session_id: str) -> bool:
    """
    True if `session_id` is chronologically the user's first-ever SimulationSession
    for `scenario_id` (ordered by started_at, falling back to created_at for sessions
    that never had started_at populated). Used to gate capstone scenarios so only a
    player's first attempt counts toward certification eligibility.
    """
    result = await db.execute(
        text("""
            SELECT s.id
            FROM simulation_sessions s
            JOIN session_participants sp ON sp.session_id = s.id
            WHERE sp.user_id = :uid AND s.scenario_id = :sid
            ORDER BY COALESCE(s.started_at, s.created_at) ASC, s.created_at ASC
            LIMIT 1
        """),
        {"uid": user_id, "sid": scenario_id},
    )
    r = result.fetchone()
    return r is not None and r.id == session_id


async def _cert_exists(db: AsyncSession, user_id: str, cert_key: str) -> bool:
    result = await db.execute(
        text("SELECT 1 FROM certifications WHERE user_id = :uid AND cert_key = :key"),
        {"uid": user_id, "key": cert_key},
    )
    return result.fetchone() is not None


async def _issue_cert(db: AsyncSession, user_id: str, cert_key: str) -> dict | None:
    if cert_key not in CERTIFICATIONS:
        return None
    if await _cert_exists(db, user_id, cert_key):
        return None

    meta = CERTIFICATIONS[cert_key]
    cert_id = str(uuid.uuid4())
    token = uuid.uuid4().hex + uuid.uuid4().hex[:16]  # 48-char token
    now = datetime.utcnow()

    await db.execute(
        text("""
            INSERT INTO certifications (id, user_id, cert_key, cert_title, cert_tier, issued_at, verify_token)
            VALUES (:id, :user_id, :cert_key, :cert_title, :cert_tier, :issued_at, :verify_token)
            ON CONFLICT (user_id, cert_key) DO NOTHING
        """),
        {
            "id": cert_id,
            "user_id": user_id,
            "cert_key": cert_key,
            "cert_title": meta["title"],
            "cert_tier": meta["tier"],
            "issued_at": now,
            "verify_token": token,
        },
    )
    await db.commit()

    logger.info("Issued cert '%s' to user %s", cert_key, user_id)
    return {"cert_key": cert_key, "title": meta["title"], "tier": meta["tier"], "icon": meta["icon"]}


async def check_and_award_certs(db: AsyncSession, user_id: str) -> list[dict]:
    """
    Run all eligibility checks for a user and issue any newly earned certs.
    Returns list of newly issued cert dicts.
    """
    newly_issued: list[dict] = []

    # ── 1. Incident Response Fundamentals ─────────────────────────────────────
    # Flagship cert: requires 3 completed scenarios averaging 60%+ score (existing
    # criterion, unchanged) AND now also requires >=70% average technique mastery
    # (new, additive — makes the credential mean something beyond raw completion).
    # Capstone-flagged scenarios (is_capstone=True) only count toward the 3-scenario
    # tally on the player's chronologically first attempt at that scenario, so
    # replaying a capstone until you get lucky can't farm this cert.
    if not await _cert_exists(db, user_id, "ir_fundamentals"):
        row = await db.execute(
            text("""
                SELECT s.id, s.scenario_id, s.team_score, sc.is_capstone
                FROM simulation_sessions s
                JOIN session_participants sp ON sp.session_id = s.id
                JOIN scenarios sc ON sc.id = s.scenario_id
                WHERE sp.user_id = :uid AND s.status = 'completed'
            """),
            {"uid": user_id},
        )
        rows = row.fetchall()

        eligible_scores: list[float] = []
        for r in rows:
            if r.is_capstone:
                is_first = await _is_first_attempt_for_scenario(db, user_id, r.scenario_id, r.id)
                if not is_first:
                    continue
            eligible_scores.append(r.team_score or 0)

        if len(eligible_scores) >= 3:
            avg_score = sum(eligible_scores) / len(eligible_scores)
            if avg_score >= 60 and await _meets_mastery_threshold(db, user_id, 70):
                cert = await _issue_cert(db, user_id, "ir_fundamentals")
                if cert:
                    newly_issued.append(cert)

    # ── 2. Certified Analyst (SOC Analyst tier = 1000 XP) ─────────────────────
    if not await _cert_exists(db, user_id, "certified_analyst"):
        row = await db.execute(
            text("SELECT xp_total FROM users WHERE id = :uid"), {"uid": user_id}
        )
        r = row.fetchone()
        if r and (r.xp_total or 0) >= 1_000:
            cert = await _issue_cert(db, user_id, "certified_analyst")
            if cert:
                newly_issued.append(cert)

    # ── 3. Red Team Operator I ────────────────────────────────────────────────
    if not await _cert_exists(db, user_id, "red_team_operator"):
        row = await db.execute(
            text("""
                SELECT COUNT(*) as cnt
                FROM red_team_sessions
                WHERE user_id = :uid AND status != 'active'
            """),
            {"uid": user_id},
        )
        r = row.fetchone()
        if r and (r.cnt or 0) >= 2:
            cert = await _issue_cert(db, user_id, "red_team_operator")
            if cert:
                newly_issued.append(cert)

    # ── 4. Ransomware Defense Specialist ──────────────────────────────────────
    if not await _cert_exists(db, user_id, "ransomware_defender"):
        row = await db.execute(
            text("""
                SELECT COUNT(*) as cnt, AVG(s.team_score) as avg_score
                FROM simulation_sessions s
                JOIN session_participants sp ON sp.session_id = s.id
                JOIN scenarios sc ON sc.id = s.scenario_id
                WHERE sp.user_id = :uid AND s.status = 'completed'
                  AND (LOWER(sc.title) LIKE '%ransomware%'
                       OR LOWER(sc.title) LIKE '%colonial%'
                       OR LOWER(sc.title) LIKE '%wanna%')
            """),
            {"uid": user_id},
        )
        r = row.fetchone()
        if r and (r.cnt or 0) >= 2 and (r.avg_score or 0) >= 65:
            cert = await _issue_cert(db, user_id, "ransomware_defender")
            if cert:
                newly_issued.append(cert)

    # ── 5. Daily Champion (7-day streak) ──────────────────────────────────────
    if not await _cert_exists(db, user_id, "daily_champion"):
        row = await db.execute(
            text("""
                SELECT current_streak FROM user_streaks WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        r = row.fetchone()
        if r and (r.current_streak or 0) >= 7:
            cert = await _issue_cert(db, user_id, "daily_champion")
            if cert:
                newly_issued.append(cert)

    # ── 6. Critical Infrastructure Defender (Colonial Pipeline) ───────────────
    if not await _cert_exists(db, user_id, "critical_infra_defender"):
        row = await db.execute(
            text("""
                SELECT COUNT(*) as cnt
                FROM simulation_sessions s
                JOIN session_participants sp ON sp.session_id = s.id
                JOIN scenarios sc ON sc.id = s.scenario_id
                WHERE sp.user_id = :uid AND s.status = 'completed'
                  AND LOWER(sc.title) LIKE '%colonial%'
            """),
            {"uid": user_id},
        )
        r = row.fetchone()
        if r and (r.cnt or 0) >= 1:
            cert = await _issue_cert(db, user_id, "critical_infra_defender")
            if cert:
                newly_issued.append(cert)

    # ── 7. Supply Chain Expert (SolarWinds) ───────────────────────────────────
    if not await _cert_exists(db, user_id, "supply_chain_expert"):
        row = await db.execute(
            text("""
                SELECT COUNT(*) as cnt
                FROM simulation_sessions s
                JOIN session_participants sp ON sp.session_id = s.id
                JOIN scenarios sc ON sc.id = s.scenario_id
                WHERE sp.user_id = :uid AND s.status = 'completed'
                  AND LOWER(sc.title) LIKE '%solar%'
            """),
            {"uid": user_id},
        )
        r = row.fetchone()
        if r and (r.cnt or 0) >= 1:
            cert = await _issue_cert(db, user_id, "supply_chain_expert")
            if cert:
                newly_issued.append(cert)

    # ── 8. Elite Threat Hunter (15k XP) ──────────────────────────────────────
    if not await _cert_exists(db, user_id, "elite_operator"):
        row = await db.execute(
            text("SELECT xp_total FROM users WHERE id = :uid"), {"uid": user_id}
        )
        r = row.fetchone()
        if r and (r.xp_total or 0) >= 15_000:
            cert = await _issue_cert(db, user_id, "elite_operator")
            if cert:
                newly_issued.append(cert)

    return newly_issued


async def get_user_certs(db: AsyncSession, user_id: str) -> list[dict]:
    """Fetch all certifications for a user, enriched with catalogue metadata."""
    result = await db.execute(
        text("""
            SELECT id, cert_key, cert_title, cert_tier, issued_at, verify_token
            FROM certifications
            WHERE user_id = :uid
            ORDER BY issued_at ASC
        """),
        {"uid": user_id},
    )
    rows = result.fetchall()

    # Mastery percentage is a live, computed-at-view-time stat (not stored on the
    # cert row) — same average-accuracy calc used to gate new ir_fundamentals
    # issuance. Computed once per call and reused across all of the user's certs.
    mastery_pct = await _average_mastery_pct(db, user_id)

    out = []
    for r in rows:
        meta = CERTIFICATIONS.get(r.cert_key, {})
        out.append({
            "id": r.id,
            "cert_key": r.cert_key,
            "title": r.cert_title,
            "subtitle": meta.get("subtitle", "Verified · BreachReplay"),
            "tier": r.cert_tier,
            "color": meta.get("color", "#6b7280"),
            "icon": meta.get("icon", "🏅"),
            "desc": meta.get("desc", ""),
            "criteria_display": meta.get("criteria_display", ""),
            "issued_at": r.issued_at.isoformat(),
            "verify_url": f"/cert/{r.verify_token}",
            "verify_token": r.verify_token,
            "mastery_pct": mastery_pct,
        })
    return out


async def verify_cert_by_token(db: AsyncSession, token: str) -> dict | None:
    """Public verification — look up a cert by its token."""
    result = await db.execute(
        text("""
            SELECT c.id, c.user_id, c.cert_key, c.cert_title, c.cert_tier, c.issued_at, c.verify_token,
                   u.full_name, u.email
            FROM certifications c
            JOIN users u ON u.id = c.user_id
            WHERE c.verify_token = :token
        """),
        {"token": token},
    )
    r = result.fetchone()
    if not r:
        return None

    meta = CERTIFICATIONS.get(r.cert_key, {})
    mastery_pct = await _average_mastery_pct(db, r.user_id)
    return {
        "valid": True,
        "title": r.cert_title,
        "subtitle": meta.get("subtitle", "Verified · BreachReplay"),
        "tier": r.cert_tier,
        "color": meta.get("color", "#6b7280"),
        "icon": meta.get("icon", "🏅"),
        "desc": meta.get("desc", ""),
        "issued_to": r.full_name or r.email.split("@")[0],
        "issued_at": r.issued_at.isoformat(),
        "verify_token": r.verify_token,
        "mastery_pct": mastery_pct,
    }


def generate_cert_pdf(cert_data: dict) -> bytes:
    """Generate a professional A4 landscape PDF certificate and return raw bytes."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm

    # Page dimensions: A4 landscape = 842 x 595 pt
    width, height = landscape(A4)

    # Parse tier accent colour → RGB floats
    tier_hex_map = {
        "bronze": "#cd7f32",
        "silver": "#c0c0c0",
        "gold": "#ffd700",
        "platinum": "#e5e4e2",
    }
    hex_color = tier_hex_map.get(cert_data.get("tier", "bronze"), cert_data.get("color", "#cd7f32"))
    hex_color = hex_color.lstrip("#")
    accent_r = int(hex_color[0:2], 16) / 255.0
    accent_g = int(hex_color[2:4], 16) / 255.0
    accent_b = int(hex_color[4:6], 16) / 255.0

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    # ── Background: dark navy ────────────────────────────────────────────────────
    c.setFillColorRGB(0x0D / 255, 0x11 / 255, 0x17 / 255)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    # ── Left accent strip (2 cm wide) ────────────────────────────────────────────
    strip_w = 2 * cm
    c.setFillColorRGB(accent_r, accent_g, accent_b)
    c.rect(0, 0, strip_w, height, fill=1, stroke=0)

    # Content starts after the strip, with padding
    left = strip_w + 1.5 * cm
    right_margin = 1.5 * cm
    center_x = (left + (width - right_margin)) / 2

    # ── BREACHREPLAY wordmark ─────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 24)
    c.setFillColorRGB(1, 1, 1)
    c.drawString(left, height - 2.5 * cm, "BREACHREPLAY")

    # ── Subtitle below wordmark ───────────────────────────────────────────────────
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawString(left, height - 3.3 * cm, "CERTIFICATE OF ACHIEVEMENT")

    # ── Horizontal rule ───────────────────────────────────────────────────────────
    rule_y = height - 4.0 * cm
    c.setStrokeColorRGB(accent_r, accent_g, accent_b)
    c.setLineWidth(1.2)
    c.line(left, rule_y, width - right_margin, rule_y)

    # ── Cert icon (text placeholder) ─────────────────────────────────────────────
    icon_text = cert_data.get("icon", "")
    icon_y = height - 6.5 * cm
    c.setFont("Helvetica-Bold", 32)
    c.setFillColorRGB(accent_r, accent_g, accent_b)
    # Emoji may not render in Helvetica — draw a styled badge instead
    tier_label = (cert_data.get("tier", "bronze")).upper()
    c.drawCentredString(center_x, icon_y, f"[ {tier_label} ]")

    # ── Awarded to ────────────────────────────────────────────────────────────────
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawCentredString(center_x, icon_y - 1.3 * cm, "Awarded to")

    c.setFont("Helvetica-Bold", 22)
    c.setFillColorRGB(1, 1, 1)
    c.drawCentredString(center_x, icon_y - 2.3 * cm, cert_data.get("issued_to", ""))

    # ── Certificate title ─────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 28)
    c.setFillColorRGB(1, 1, 1)
    c.drawCentredString(center_x, icon_y - 3.6 * cm, cert_data.get("title", ""))

    # ── Subtitle ──────────────────────────────────────────────────────────────────
    c.setFont("Helvetica", 12)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawCentredString(center_x, icon_y - 4.5 * cm, cert_data.get("subtitle", ""))

    # ── Description (word-wrapped) ────────────────────────────────────────────────
    desc = cert_data.get("desc", "")
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    max_chars = 90
    desc_y = icon_y - 5.5 * cm
    if len(desc) > max_chars:
        # Simple two-line split at word boundary near midpoint
        split_idx = desc.rfind(" ", 0, max_chars)
        if split_idx == -1:
            split_idx = max_chars
        c.drawCentredString(center_x, desc_y, desc[:split_idx].strip())
        c.drawCentredString(center_x, desc_y - 0.5 * cm, desc[split_idx:].strip())
        desc_y -= 0.5 * cm
    else:
        c.drawCentredString(center_x, desc_y, desc)

    # ── Issue date ────────────────────────────────────────────────────────────────
    issued_at = cert_data.get("issued_at", "")
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(issued_at)
        issued_str = dt.strftime("%B %d, %Y")
    except Exception:
        issued_str = issued_at

    date_y = desc_y - 1.2 * cm
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawCentredString(center_x, date_y, f"Issued: {issued_str}")

    # ── Verify URL ────────────────────────────────────────────────────────────────
    verify_token = cert_data.get("verify_token", "")
    verify_url = f"breachreplay.com/cert/{verify_token}"
    url_y = date_y - 0.8 * cm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(center_x, url_y, f"Verify at: {verify_url}")

    # ── Verified Authentic badge ──────────────────────────────────────────────────
    badge_y = url_y - 0.9 * cm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColorRGB(0.0, 0.75, 0.4)
    c.drawCentredString(center_x, badge_y, "✓  VERIFIED AUTHENTIC")

    c.save()
    return buf.getvalue()
