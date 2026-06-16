from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_HTML_WRAPPER = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{subject}</title>
<style>
  body {{ margin:0; padding:0; background:#0f172a; font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; }}
  .outer {{ background:#0f172a; padding: 40px 20px; }}
  .card  {{ max-width:600px; margin:0 auto; background:#1e293b; border-radius:8px; border:1px solid #334155; overflow:hidden; }}
  .header {{ background:#0f172a; padding:24px 32px; border-bottom:2px solid #ef4444; }}
  .logo   {{ font-size:12px; font-weight:900; letter-spacing:0.2em; color:#ef4444; text-transform:uppercase; }}
  .body   {{ padding:32px; color:#cbd5e1; font-size:14px; line-height:1.6; }}
  .body h2 {{ color:#f1f5f9; font-size:20px; margin:0 0 16px; font-weight:700; }}
  .metric {{ background:#0f172a; border:1px solid #334155; border-radius:6px; padding:16px 20px; margin:20px 0; }}
  .metric-label {{ font-size:10px; text-transform:uppercase; letter-spacing:0.1em; color:#64748b; font-weight:700; }}
  .metric-value {{ font-size:32px; font-weight:900; color:#f1f5f9; font-family:monospace; margin-top:4px; }}
  .cta {{ display:block; margin:24px 0; background:#ef4444; color:#fff; text-align:center;
          padding:14px 24px; border-radius:6px; text-decoration:none; font-weight:700;
          font-size:13px; letter-spacing:0.05em; text-transform:uppercase; }}
  .footer {{ background:#0f172a; padding:16px 32px; border-top:1px solid #1e293b;
             font-size:11px; color:#475569; text-align:center; }}
  .tag {{ display:inline-block; background:#1e3a8a; color:#93c5fd; border-radius:4px;
          padding:2px 8px; font-size:11px; font-weight:700; font-family:monospace;
          margin:2px; }}
</style>
</head>
<body>
<div class="outer">
  <div class="card">
    <div class="header">
      <div class="logo">⬡ Breach Replay</div>
    </div>
    <div class="body">
      {body}
    </div>
    <div class="footer">
      BreachReplay &nbsp;·&nbsp; Cybersecurity Incident Response Training &nbsp;·&nbsp;
      <a href="{frontend_url}" style="color:#3b82f6;">breachreplay.io</a>
    </div>
  </div>
</div>
</body>
</html>
"""


def _send(to_email: str, subject: str, html_body: str) -> bool:
    if not settings.SENDGRID_API_KEY:
        logger.info("SendGrid not configured — skipping email to %s", to_email)
        return False
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=settings.FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
            html_content=html_body,
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info("Email sent to %s status=%s", to_email, response.status_code)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def send_debrief_ready_email(
    to_email: str,
    session_id: str,
    scenario_title: str,
    score: Optional[float],
    correct: int,
    total: int,
) -> bool:
    subject = f"BreachReplay Debrief Ready — {scenario_title}"
    score_display = f"{score}%" if score is not None else "—"
    color = "#10b981" if (score or 0) >= 80 else ("#f59e0b" if (score or 0) >= 60 else "#ef4444")
    body = f"""
<h2>Your Simulation Debrief Is Ready</h2>
<p>Your team has completed the <strong style="color:#f1f5f9;">{scenario_title}</strong>
tabletop simulation. Claude AI has generated your full gap analysis and compliance evidence package.</p>

<div class="metric">
  <div class="metric-label">NIST Compliance Score</div>
  <div class="metric-value" style="color:{color};">{score_display}</div>
</div>

<p style="font-size:13px; color:#94a3b8;">
  <span class="tag">{correct}/{total} Correct Decisions</span>
</p>

<p>Your debrief includes:</p>
<ul style="color:#94a3b8; font-size:13px;">
  <li>Decision-by-decision scoring with NIST SP 800-61 rationale</li>
  <li>MITRE ATT&amp;CK technique coverage map</li>
  <li>Prioritized remediation checklist with owner assignment</li>
  <li>Audit-ready compliance evidence package (PDF export)</li>
</ul>

<a class="cta" href="{settings.FRONTEND_URL}/session/{session_id}/debrief">
  View Debrief Report →
</a>

<p style="font-size:11px; color:#475569;">
  This report satisfies documented IR training requirements under NIST SP 800-61 Rev 2,
  SOC 2 Type II (CC7.3), and ISO 27001 (A.7.2.2).
</p>
"""
    html = _HTML_WRAPPER.format(subject=subject, body=body, frontend_url=settings.FRONTEND_URL)
    return _send(to_email, subject, html)


def send_team_invite_email(
    to_email: str,
    inviter_name: str,
    session_id: str,
    scenario_title: str,
) -> bool:
    subject = f"{inviter_name} invited you to a BreachReplay simulation"
    body = f"""
<h2>You've Been Invited to a Cyber Incident Simulation</h2>
<p><strong style="color:#f1f5f9;">{inviter_name}</strong> has invited you to join a
live tabletop simulation session on BreachReplay.</p>

<div class="metric" style="border-color:#1e3a8a;">
  <div class="metric-label">Scenario</div>
  <div style="font-size:16px; font-weight:700; color:#93c5fd; margin-top:6px;">
    {scenario_title}
  </div>
</div>

<p style="font-size:13px; color:#94a3b8;">
  You will be assigned a role in the incident response team. Make decisions at critical
  junctures and help your team contain the breach.
</p>

<a class="cta" href="{settings.FRONTEND_URL}/session/{session_id}/lobby">
  Join Simulation →
</a>

<p style="font-size:11px; color:#475569;">
  If you don't have a BreachReplay account yet, you'll be prompted to create one when you
  click the link above.
</p>
"""
    html = _HTML_WRAPPER.format(subject=subject, body=body, frontend_url=settings.FRONTEND_URL)
    return _send(to_email, subject, html)


def send_team_invite_email_v2(
    to_email: str,
    inviter_name: str,
    team_name: str,
    join_url: str,
) -> bool:
    subject = f"{inviter_name} invited you to join '{team_name}' on BreachReplay"
    body = f"""
<h2>You've Been Invited to a Team</h2>
<p><strong style="color:#f1f5f9;">{inviter_name}</strong> has invited you to join the
<strong style="color:#f1f5f9;">{team_name}</strong> team on BreachReplay.</p>

<div class="metric" style="border-color:#1e3a8a;">
  <div class="metric-label">Team</div>
  <div style="font-size:18px; font-weight:700; color:#93c5fd; margin-top:6px;">{team_name}</div>
</div>

<p style="font-size:13px; color:#94a3b8;">
  BreachReplay is a live cybersecurity tabletop simulation platform. Your team competes
  on real breach scenarios — Colonial Pipeline, SolarWinds, MGM — and earns XP toward a
  shared team leaderboard.
</p>

<a class="cta" href="{join_url}">Join the Team →</a>

<p style="font-size:11px; color:#475569;">
  If you don't have a BreachReplay account, you'll be prompted to create one when you click the link.
</p>
"""
    html = _HTML_WRAPPER.format(subject=subject, body=body, frontend_url=settings.FRONTEND_URL)
    return _send(to_email, subject, html)


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    subject = "BreachReplay — Password Reset Request"
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
    body = f"""
<h2>Password Reset Request</h2>
<p>We received a request to reset the password for your BreachReplay account
associated with <strong style="color:#f1f5f9;">{to_email}</strong>.</p>

<a class="cta" href="{reset_url}">Reset Password →</a>

<p style="font-size:11px; color:#475569;">
  This link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes.
  If you did not request a password reset, you can safely ignore this email.
</p>
"""
    html = _HTML_WRAPPER.format(subject=subject, body=body, frontend_url=settings.FRONTEND_URL)
    return _send(to_email, subject, html)


def send_weekly_slack_digest_email(to_email: str, org_name: str, scenarios_ingested: int) -> bool:
    subject = f"BreachReplay Weekly Digest — {scenarios_ingested} New Scenarios"
    body = f"""
<h2>Weekly Scenario Digest — {org_name}</h2>
<p>The BreachReplay automated pipeline has processed <strong style="color:#f1f5f9;">
{scenarios_ingested} new breach scenarios</strong> this week from CISA, SEC EDGAR,
HHS, and threat intelligence feeds.</p>

<a class="cta" href="{settings.FRONTEND_URL}/scenarios">Browse New Scenarios →</a>

<p style="font-size:11px; color:#475569;">
  Your team's scenario library is growing. Each approved scenario is tagged with MITRE
  ATT&amp;CK techniques and NIST SP 800-61 controls for compliance tracking.
</p>
"""
    html = _HTML_WRAPPER.format(subject=subject, body=body, frontend_url=settings.FRONTEND_URL)
    return _send(to_email, subject, html)
