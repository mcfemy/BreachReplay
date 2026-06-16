"""
Red Team Mode — play as the attacker.
The user chooses TTPs (MITRE ATT&CK tactics), executes moves,
and an AI blue-team responds dynamically. Stealth vs Impact tradeoff.
"""
import uuid
import random
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.db.session import get_db
from app.models.red_team import RedTeamSession, RedTeamMove
from app.models.scenario import Scenario
from app.models.user import User
from app.core.security import get_current_user
from app.core.logging import get_logger
from app.services import xp_service

router = APIRouter(prefix="/redteam", tags=["redteam"])
logger = get_logger(__name__)


# ── Attack taxonomy (MITRE ATT&CK phases + available moves per phase) ──────────

ATTACK_PHASES = [
    "initial_access",
    "execution",
    "persistence",
    "privilege_escalation",
    "defense_evasion",
    "credential_access",
    "discovery",
    "lateral_movement",
    "collection",
    "exfiltration",
    "impact",
]

PHASE_MOVES: dict[str, list[dict]] = {
    "initial_access": [
        {"tactic": "Spearphishing Link", "technique_id": "T1566.002", "tool": "GoPhish",
         "description": "Send targeted phishing email to a specific employee found via LinkedIn",
         "stealth": 8, "impact": 6, "detection_risk": 0.25,
         "success_consequence": "Employee clicks link, installs dropper. You have a foothold on CORP-WKS-22.",
         "fail_consequence": "Email flagged by SEG. Blue team now has your phishing domain as an IOC."},
        {"tactic": "Valid Accounts — VPN Credentials", "technique_id": "T1078", "tool": "Credential Stuffing",
         "description": "Use credentials from a dark web dump to authenticate to the VPN",
         "stealth": 9, "impact": 7, "detection_risk": 0.15,
         "success_consequence": "VPN auth succeeds with svc_backup. You're inside the network with no malware on disk.",
         "fail_consequence": "Account lockout triggered. IT helpdesk ticket created — you've been noticed."},
        {"tactic": "Supply Chain Compromise", "technique_id": "T1195.002", "tool": "Trojanized Update",
         "description": "Compromise a software vendor's update pipeline to deliver a backdoored update",
         "stealth": 10, "impact": 9, "detection_risk": 0.05,
         "success_consequence": "Update delivered to 847 hosts. Your backdoor is signed by a trusted vendor.",
         "fail_consequence": "Vendor's CI/CD security catches the tampered package before distribution."},
        {"tactic": "Drive-by Compromise", "technique_id": "T1189", "tool": "Browser Exploit Kit",
         "description": "Compromise a popular industry forum — watering hole attack targeting sector employees",
         "stealth": 7, "impact": 5, "detection_risk": 0.35,
         "success_consequence": "3 employees from the target org visited the forum. Browser exploit executes on one.",
         "fail_consequence": "Browser is patched. Exploit fails silently — no foothold gained."},
    ],
    "execution": [
        {"tactic": "PowerShell", "technique_id": "T1059.001", "tool": "PowerShell Empire",
         "description": "Execute encoded PowerShell to download second-stage payload",
         "stealth": 5, "impact": 7, "detection_risk": 0.45,
         "success_consequence": "Empire agent running in memory. No file dropped on disk.",
         "fail_consequence": "AMSI blocks the encoded payload. EDR alerts on suspicious PowerShell args."},
        {"tactic": "Windows Management Instrumentation", "technique_id": "T1047", "tool": "WMIexec",
         "description": "Execute commands via WMI — fileless, uses legitimate Windows feature",
         "stealth": 8, "impact": 6, "detection_risk": 0.20,
         "success_consequence": "Command executed via WMI. No new process spawned — looks like normal admin activity.",
         "fail_consequence": "WMI activity logged by Sysmon. Blue team correlates with prior VPN anomaly."},
        {"tactic": "Scheduled Task", "technique_id": "T1053.005", "tool": "schtasks.exe",
         "description": "Create a scheduled task named 'WindowsUpdateHelper' for persistence and execution",
         "stealth": 6, "impact": 7, "detection_risk": 0.30,
         "success_consequence": "Task created on 6 hosts. Detonation set for 03:00 — you've bought time.",
         "fail_consequence": "Task creation logged by SIEM. Unusual binary hash flagged."},
    ],
    "persistence": [
        {"tactic": "Create Account", "technique_id": "T1136.001", "tool": "net.exe",
         "description": "Create a hidden domain admin account 'svc_update01' for persistent access",
         "stealth": 6, "impact": 8, "detection_risk": 0.40,
         "success_consequence": "New domain admin created. Even if your current session is burned, you have a backdoor.",
         "fail_consequence": "SIEM fires on new admin account with no ticket. Account immediately disabled."},
        {"tactic": "Boot or Logon Autostart", "technique_id": "T1547.001", "tool": "Registry Run Key",
         "description": "Add malware to HKCU Run key — survives reboots, runs as current user",
         "stealth": 7, "impact": 6, "detection_risk": 0.25,
         "success_consequence": "Persistence established via registry. Will survive a reboot.",
         "fail_consequence": "EDR flags Run key modification. Registry change rolled back automatically."},
        {"tactic": "Server Software Component — Web Shell", "technique_id": "T1505.003", "tool": "China Chopper",
         "description": "Drop a web shell on an internet-facing IIS server for backup access",
         "stealth": 8, "impact": 7, "detection_risk": 0.20,
         "success_consequence": "Web shell deployed. You have HTTP-based backup access even if VPN is blocked.",
         "fail_consequence": "WAF blocks the web shell upload. File hash blacklisted."},
    ],
    "privilege_escalation": [
        {"tactic": "OS Credential Dumping — LSASS", "technique_id": "T1003.001", "tool": "Mimikatz",
         "description": "Dump LSASS memory to extract NTLM hashes and Kerberos tickets",
         "stealth": 4, "impact": 10, "detection_risk": 0.55,
         "success_consequence": "Full domain credential set extracted. You now have hashes for every logged-in user.",
         "fail_consequence": "EDR fires immediately on LSASS memory access. Credential Protection is enabled."},
        {"tactic": "Kerberoasting", "technique_id": "T1558.003", "tool": "Rubeus",
         "description": "Request Kerberos service tickets for offline cracking — very low noise",
         "stealth": 9, "impact": 7, "detection_risk": 0.10,
         "success_consequence": "Service ticket for svc_sql cracked offline. You have DA-equivalent credentials.",
         "fail_consequence": "Service account has a 30-character random password. Cracking infeasible."},
        {"tactic": "Exploitation for Privilege Escalation — PrintNightmare", "technique_id": "T1068", "tool": "CVE-2021-34527",
         "description": "Exploit unpatched Print Spooler service for SYSTEM-level code execution",
         "stealth": 6, "impact": 9, "detection_risk": 0.35,
         "success_consequence": "SYSTEM shell obtained via Print Spooler exploit. Patch was never applied.",
         "fail_consequence": "Patch was applied. Exploit crashes the spooler — blue team notices."},
    ],
    "defense_evasion": [
        {"tactic": "Disable or Modify Tools", "technique_id": "T1562.001", "tool": "Group Policy",
         "description": "Modify Group Policy to disable Windows Defender across all workstations",
         "stealth": 5, "impact": 9, "detection_risk": 0.50,
         "success_consequence": "Defender disabled on 200+ endpoints. Your malware runs uninhibited.",
         "fail_consequence": "GPO change triggers SIEM alert. Change immediately reverted by blue team."},
        {"tactic": "Indicator Removal — Clear Windows Event Logs", "technique_id": "T1070.001", "tool": "wevtutil",
         "description": "Clear Security, System, and Application event logs to erase evidence",
         "stealth": 5, "impact": 5, "detection_risk": 0.60,
         "success_consequence": "Logs cleared. Your movements in the past hour are gone from Windows Event Log.",
         "fail_consequence": "Log clearing itself is an auditable event — SIEM fires immediately."},
        {"tactic": "Obfuscated Files or Information", "technique_id": "T1027", "tool": "Invoke-Obfuscation",
         "description": "Obfuscate all scripts and binaries to evade signature-based detection",
         "stealth": 8, "impact": 4, "detection_risk": 0.15,
         "success_consequence": "All tools obfuscated. AV/EDR signatures no longer match.",
         "fail_consequence": "Heuristic engine catches behavioral patterns despite obfuscation."},
    ],
    "credential_access": [
        {"tactic": "Brute Force — Password Spraying", "technique_id": "T1110.003", "tool": "Spray",
         "description": "Password spray with 'Winter2024!' across all domain accounts — one attempt per account",
         "stealth": 7, "impact": 7, "detection_risk": 0.25,
         "success_consequence": "17 accounts matched the password. You now have valid credentials for multiple users.",
         "fail_consequence": "Login failures rate-limited. Security team notified of unusual pattern."},
        {"tactic": "Forge Web Credentials — SAML Golden Ticket", "technique_id": "T1606.002", "tool": "AADInternals",
         "description": "Forge a SAML token for Azure AD SSO — valid for any cloud resource",
         "stealth": 9, "impact": 10, "detection_risk": 0.15,
         "success_consequence": "SAML token forged. You can impersonate any user across all cloud apps.",
         "fail_consequence": "Azure AD Conditional Access blocks token from unexpected location."},
    ],
    "discovery": [
        {"tactic": "Network Service Discovery", "technique_id": "T1046", "tool": "nmap",
         "description": "Scan the internal network to map live hosts, open ports, and services",
         "stealth": 3, "impact": 6, "detection_risk": 0.65,
         "success_consequence": "Full network map obtained. OT historian at 10.40.0.12 identified.",
         "fail_consequence": "Port scan detected by IDS. Your source IP is now blacklisted internally."},
        {"tactic": "Account Discovery — Domain Account", "technique_id": "T1087.002", "tool": "BloodHound",
         "description": "Run BloodHound to map AD attack paths and identify shortest path to DA",
         "stealth": 7, "impact": 8, "detection_risk": 0.25,
         "success_consequence": "BloodHound reveals a direct path to Domain Admin through 2 hops.",
         "fail_consequence": "LDAP query volume triggers anomaly detection. DC logs the enumeration."},
    ],
    "lateral_movement": [
        {"tactic": "Remote Services — RDP", "technique_id": "T1021.001", "tool": "mstsc / xfreerdp",
         "description": "RDP to 14 hosts using harvested credentials — fast lateral spread",
         "stealth": 4, "impact": 9, "detection_risk": 0.55,
         "success_consequence": "14 hosts compromised via RDP. You control a significant portion of the network.",
         "fail_consequence": "Mass RDP sessions in 8 minutes flagged by SIEM. Source DC isolated."},
        {"tactic": "Pass the Hash", "technique_id": "T1550.002", "tool": "Impacket",
         "description": "Use harvested NTLM hashes to authenticate without cracking — no password needed",
         "stealth": 7, "impact": 8, "detection_risk": 0.30,
         "success_consequence": "PtH successful. Moved laterally to 6 targets without triggering lockouts.",
         "fail_consequence": "Protected Users security group blocks NTLM auth for privileged accounts."},
        {"tactic": "Exploitation of Remote Services", "technique_id": "T1210", "tool": "EternalBlue (MS17-010)",
         "description": "Exploit unpatched SMB vulnerability to move laterally without credentials",
         "stealth": 3, "impact": 10, "detection_risk": 0.70,
         "success_consequence": "EternalBlue succeeds on 3 unpatched legacy servers — SYSTEM access on each.",
         "fail_consequence": "All systems patched. Exploit attempt generates massive IDS alert."},
    ],
    "collection": [
        {"tactic": "Data from Local System", "technique_id": "T1005", "tool": "PowerShell",
         "description": "Search and stage financial records, network diagrams, and credential stores",
         "stealth": 7, "impact": 8, "detection_risk": 0.20,
         "success_consequence": "40GB archive staged containing Q2 financials and full network topology.",
         "fail_consequence": "DLP solution detects bulk file access pattern and raises alert."},
        {"tactic": "Email Collection", "technique_id": "T1114.002", "tool": "MailSniper",
         "description": "Harvest executive email via Exchange Web Services using forged SAML token",
         "stealth": 8, "impact": 9, "detection_risk": 0.20,
         "success_consequence": "90 days of CISO and CEO emails collected. M&A plans and incident data captured.",
         "fail_consequence": "EWS activity from unexpected IP flagged by Microsoft Defender for O365."},
    ],
    "exfiltration": [
        {"tactic": "Exfiltration Over C2 Channel", "technique_id": "T1041", "tool": "Cobalt Strike Beacon",
         "description": "Exfiltrate staged data via encrypted C2 channel over HTTPS — blends with normal traffic",
         "stealth": 8, "impact": 9, "detection_risk": 0.20,
         "success_consequence": "93GB transferred over 20 minutes. DLP didn't catch HTTPS to a new domain.",
         "fail_consequence": "Firewall TI feed matches C2 IP. Connection blocked. Data not exfiltrated."},
        {"tactic": "Exfiltration Over Alternative Protocol — DNS Tunneling", "technique_id": "T1048.001", "tool": "iodine",
         "description": "Encode data in DNS queries — extremely slow but nearly invisible",
         "stealth": 10, "impact": 6, "detection_risk": 0.08,
         "success_consequence": "4.2GB exfiltrated over 90 days via DNS. Zero alerts triggered.",
         "fail_consequence": "DNS anomaly detection catches unusually long query strings."},
    ],
    "impact": [
        {"tactic": "Data Encrypted for Impact — Ransomware", "technique_id": "T1486", "tool": "DarkSide Ransomware",
         "description": "Deploy ransomware across all compromised hosts simultaneously",
         "stealth": 0, "impact": 10, "detection_risk": 1.0,
         "success_consequence": "45 hosts encrypted. $4.4M ransom demand dropped. Pipeline operations halted.",
         "fail_consequence": "EDR detects encryption behavior and kills ransomware process on most hosts."},
        {"tactic": "Defacement", "technique_id": "T1491", "tool": "Custom Script",
         "description": "Replace public-facing web content with attacker message",
         "stealth": 0, "impact": 7, "detection_risk": 1.0,
         "success_consequence": "Website defaced. Reputational damage and panic ensues.",
         "fail_consequence": "CDN serves cached version. Content quickly restored from backup."},
        {"tactic": "Inhibit System Recovery", "technique_id": "T1490", "tool": "vssadmin",
         "description": "Delete all Volume Shadow Copies to prevent recovery without paying ransom",
         "stealth": 2, "impact": 10, "detection_risk": 0.80,
         "success_consequence": "All shadow copies deleted on 26 hosts. Recovery requires paying or restoring from offsite.",
         "fail_consequence": "EDR catches vssadmin and kills the process before completion."},
    ],
}


# ── Schemas ────────────────────────────────────────────────────────────────────

class StartRedTeamRequest(BaseModel):
    scenario_id: str


class ExecuteMoveRequest(BaseModel):
    session_id: str
    phase: str
    tactic: str
    technique_id: Optional[str] = None


class RedTeamSessionOut(BaseModel):
    id: str
    scenario_id: str
    scenario_title: str
    current_phase: str
    phases_completed: list
    stealth_score: int
    impact_score: int
    status: str
    move_count: int
    blue_team_detections: list
    available_moves: list[dict]


# ── Blue team AI response engine ───────────────────────────────────────────────

def _blue_team_response(move: dict, detected: bool, phase: str) -> str:
    """Generate a realistic blue team reaction to an attacker move."""
    if not detected:
        responses = [
            f"Blue team sees nothing. The {move['tool']} activity blends into normal traffic.",
            f"SOC analyst glances at the dashboard — no alert fires. Your {phase} phase is invisible.",
            f"SIEM ingests the logs but no rule matches. Blue team is focused on a false positive elsewhere.",
            f"Threat hunter is off shift. Nobody is watching the {phase} activity.",
        ]
    else:
        responses = [
            f"ALERT: SOC analyst fires on '{move['tactic']}' — EDR rule triggered on {move.get('tool', 'unknown tool')}. Blue team has your TTPs.",
            f"INCIDENT DECLARED: {phase.upper()} detected. Blue team correlating logs from the past 2 hours.",
            f"THREAT INTEL HIT: {move.get('technique_id', '')} matches an active threat actor profile. CISO notified.",
            f"CONTAINMENT: Blue team isolating affected hosts. Your {phase} foothold may be burning.",
            f"DETECTION: Anomaly engine fired on {move['tactic']}. Stealth score dropping — blue team is onto you.",
        ]
    return random.choice(responses)


def _get_next_phase(current: str, phases_completed: list) -> str:
    """Suggest the natural next MITRE phase."""
    for phase in ATTACK_PHASES:
        if phase not in phases_completed and phase != current:
            return phase
    return current


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/scenarios")
async def list_redteam_scenarios(
    db: AsyncSession = Depends(get_db),
):
    """List approved scenarios available for red team mode."""
    result = await db.execute(
        select(Scenario)
        .where(Scenario.status == "approved")
        .order_by(Scenario.difficulty)
    )
    scenarios = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "difficulty": s.difficulty,
            "industry_vertical": s.industry_vertical,
            "initial_access_vector": s.initial_access_vector,
            "mitre_techniques": s.mitre_techniques or [],
            "description": s.description,
        }
        for s in scenarios
    ]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def start_red_team_session(
    payload: StartRedTeamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a new red team session for a given scenario."""
    result = await db.execute(
        select(Scenario).where(Scenario.id == payload.scenario_id, Scenario.status == "approved")
    )
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    session = RedTeamSession(
        id=str(uuid.uuid4()),
        scenario_id=scenario.id,
        user_id=current_user.id,
        current_phase="initial_access",
        phases_completed=[],
        objectives_achieved=[],
        objectives_failed=[],
        blue_team_detections=[],
        started_at=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {
        "session_id": session.id,
        "scenario_title": scenario.title,
        "scenario_difficulty": scenario.difficulty,
        "initial_access_vector": scenario.initial_access_vector,
        "mitre_techniques": scenario.mitre_techniques or [],
        "current_phase": session.current_phase,
        "stealth_score": session.stealth_score,
        "impact_score": session.impact_score,
        "available_moves": PHASE_MOVES.get("initial_access", []),
        "objective": "Gain a foothold inside the target network.",
        "intel_brief": (
            f"Target: {scenario.title}\n"
            f"Industry: {(scenario.industry_vertical or 'unknown').upper()}\n"
            f"Known assets: {', '.join((scenario.affected_asset_types or [])[:4])}\n"
            f"Likely defences: EDR, SIEM, network monitoring\n"
            f"Your mission: compromise the target, achieve maximum impact while staying undetected."
        ),
    }


@router.post("/sessions/{session_id}/move")
async def execute_move(
    session_id: str,
    payload: ExecuteMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute an attacker move. Returns outcome, blue team response, updated state."""
    result = await db.execute(
        select(RedTeamSession)
        .options(selectinload(RedTeamSession.moves))
        .where(
            RedTeamSession.id == session_id,
            RedTeamSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}")

    # Find the move definition
    phase_moves = PHASE_MOVES.get(payload.phase, [])
    move_def = next((m for m in phase_moves if m["tactic"] == payload.tactic), None)
    if not move_def:
        raise HTTPException(status_code=400, detail="Unknown tactic for this phase")

    # Determine success and detection
    # Success probability based on current stealth (higher stealth = better execution)
    stealth_factor = session.stealth_score / 100
    base_success = 0.70 + (stealth_factor * 0.20)
    succeeded = random.random() < base_success

    detection_roll = random.random()
    # Being detected is more likely when stealth is low
    adjusted_detection_risk = move_def["detection_risk"] * (1 + (1 - stealth_factor))
    detected = detection_roll < adjusted_detection_risk

    # Calculate deltas
    if succeeded:
        impact_delta = move_def["impact"]
        consequence = move_def["success_consequence"]
    else:
        impact_delta = 0
        consequence = move_def["fail_consequence"]

    stealth_delta = 0
    if detected:
        stealth_delta = -(15 + random.randint(0, 10))
        impact_delta = max(0, impact_delta - 2)

    # Update session state
    new_stealth = max(0, session.stealth_score + stealth_delta)
    new_impact = min(100, session.impact_score + impact_delta)

    blue_response = _blue_team_response(move_def, detected, payload.phase)

    # Record the move
    move_number = len(session.moves) + 1 if session.moves else 1
    move = RedTeamMove(
        id=str(uuid.uuid4()),
        session_id=session.id,
        move_number=move_number,
        phase=payload.phase,
        tactic=payload.tactic,
        technique_id=move_def.get("technique_id"),
        tool_used=move_def.get("tool"),
        target=payload.tactic,
        succeeded=succeeded,
        detected=detected,
        blue_team_response=blue_response,
        consequence=consequence,
        stealth_delta=stealth_delta,
        impact_delta=impact_delta,
        created_at=datetime.utcnow(),
    )
    db.add(move)

    # Update session
    session.stealth_score = new_stealth
    session.impact_score = new_impact
    session.current_phase = payload.phase

    detections = list(session.blue_team_detections or [])
    if detected:
        detections.append({"phase": payload.phase, "tactic": payload.tactic, "response": blue_response})
    session.blue_team_detections = detections

    phases_done = list(session.phases_completed or [])
    if payload.phase not in phases_done and succeeded:
        phases_done.append(payload.phase)
    session.phases_completed = phases_done

    # Check win/loss conditions
    new_status = "active"
    outcome_message = ""
    if new_stealth == 0:
        new_status = "caught"
        session.final_score = new_impact * 10
        outcome_message = "BURNED: Blue team has full visibility of your operation. You've been caught and contained."
    elif new_impact >= 90 and "impact" in phases_done:
        new_status = "success"
        session.final_score = new_impact * 10 + new_stealth * 5
        outcome_message = "MISSION COMPLETE: Maximum impact achieved. The target is compromised."

    xp_earned = 0
    new_achievements: list = []
    xp_leveled_up = False
    new_tier = None

    if new_status != "active":
        session.status = new_status
        session.completed_at = datetime.utcnow()
        await db.commit()

        # Award XP on game end
        xp_earned = max(10, new_impact * 2 + new_stealth)
        xp_result = await xp_service.award_xp(
            db, current_user.id, xp_earned, "redteam",
            f"Red Team {'success' if new_status == 'success' else 'operation'} — impact {new_impact}, stealth {new_stealth}",
            source_id=session_id,
        )
        # Count user's total red team sessions
        ops_count_result = await db.execute(
            select(RedTeamSession)
            .where(RedTeamSession.user_id == current_user.id, RedTeamSession.status != "active")
        )
        total_ops = len(ops_count_result.scalars().all())
        new_achievements = await xp_service.check_redteam_achievements(
            db, current_user.id, new_stealth, new_impact, total_ops
        )
        new_achievements += await xp_service.check_xp_milestones(db, current_user.id, xp_result.get("new_xp", 0))
        xp_leveled_up = xp_result.get("leveled_up", False)
        new_tier = xp_result.get("new_tier")
    else:
        await db.commit()

    # Suggest next moves
    next_phase = _get_next_phase(payload.phase, phases_done)
    available_moves = PHASE_MOVES.get(next_phase if succeeded else payload.phase, [])

    return {
        "move_number": move_number,
        "tactic": payload.tactic,
        "technique_id": move_def.get("technique_id"),
        "tool": move_def.get("tool"),
        "succeeded": succeeded,
        "detected": detected,
        "consequence": consequence,
        "blue_team_response": blue_response,
        "stealth_score": new_stealth,
        "stealth_delta": stealth_delta,
        "impact_score": new_impact,
        "impact_delta": impact_delta,
        "phases_completed": phases_done,
        "current_phase": payload.phase,
        "suggested_next_phase": next_phase if succeeded else payload.phase,
        "available_moves": available_moves,
        "session_status": new_status,
        "outcome_message": outcome_message,
        "final_score": session.final_score if new_status != "active" else None,
        "xp_earned": xp_earned,
        "new_achievements": new_achievements,
        "leveled_up": xp_leveled_up,
        "new_tier": new_tier,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current state of a red team session."""
    result = await db.execute(
        select(RedTeamSession)
        .options(selectinload(RedTeamSession.moves))
        .where(
            RedTeamSession.id == session_id,
            RedTeamSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sc_result = await db.execute(select(Scenario.title).where(Scenario.id == session.scenario_id))
    title = sc_result.scalar_one_or_none() or "Unknown"

    available_moves = PHASE_MOVES.get(session.current_phase, [])

    return {
        "id": session.id,
        "scenario_title": title,
        "current_phase": session.current_phase,
        "phases_completed": session.phases_completed or [],
        "stealth_score": session.stealth_score,
        "impact_score": session.impact_score,
        "status": session.status,
        "final_score": session.final_score,
        "blue_team_detections": session.blue_team_detections or [],
        "available_moves": available_moves,
        "move_count": len(session.moves) if session.moves else 0,
    }


@router.get("/sessions")
async def list_my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List user's red team sessions."""
    result = await db.execute(
        select(RedTeamSession, Scenario.title)
        .join(Scenario, RedTeamSession.scenario_id == Scenario.id)
        .where(RedTeamSession.user_id == current_user.id)
        .order_by(desc(RedTeamSession.started_at))
        .limit(20)
    )
    rows = result.all()
    return [
        {
            "id": s.id,
            "scenario_title": title,
            "status": s.status,
            "stealth_score": s.stealth_score,
            "impact_score": s.impact_score,
            "final_score": s.final_score,
            "phases_completed": len(s.phases_completed or []),
            "started_at": s.started_at.isoformat(),
        }
        for s, title in rows
    ]
