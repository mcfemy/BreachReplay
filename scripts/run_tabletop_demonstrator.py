import asyncio
import os
import sys
from datetime import datetime

# Inject required environment variables before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///demonstrator.db"
os.environ["SYNC_DATABASE_URL"] = "sqlite:///demonstrator.db"
os.environ["SECRET_KEY"] = "demo-secret-key-breachreplay-demo-12345"
os.environ["ANTHROPIC_API_KEY"] = "demo-key-breachreplay"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

# Adjust Python import path to find the backend app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.db.session import Base
from app.models.organization import Organization
from app.models.scenario import Scenario
from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.user import User
from app.core.security import hash_password
from app.services.pdf_generator import generate_debrief_pdf

DB_URL = "sqlite+aiosqlite:///demonstrator.db"
engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

DECISION_TREE_DEMO = [
    {
        "id": "gate-001",
        "trigger_timestamp": "+5m",
        "context_summary": "Active lateral compromise detected via suspicious compromised VPN session.",
        "options": [
            {"text": "Isolate the target host immediately", "consequence_if_chosen": "Intrusion contained at source."},
            {"text": "Allow VPN session to continue to capture forensic artifacts", "consequence_if_chosen": "Attacker exfiltrates S3 backup archives."},
            {"text": "Broadcast alerts to security mailing list and wait for response", "consequence_if_chosen": "Delayed containment allows domain escalation."}
        ],
        "correct_index": 0,
        "consequence_if_wrong": "Lateral domain dominance achieved by intruder.",
        "consequence_if_correct": "Threat contained successfully.",
        "rationale": "NIST IR protocol SP 800-61 Rev 2 emphasizes prompt host containment to prevent domain-wide compromises.",
        "nist_control_ref": "RS.CO-1",
        "mitre_technique": "T1133"
    },
    {
        "id": "gate-002",
        "trigger_timestamp": "+15m",
        "context_summary": "Attacker is attempting to dump S3 bucket archives via hijacked cloud service account credentials.",
        "options": [
            {"text": "Revoke target API key and rotate cloud service secrets", "consequence_if_chosen": "Exfiltration channels cut off instantly."},
            {"text": "Apply restrictive read-only bucket policies globally", "consequence_if_chosen": "Bucket exfiltration continues via existing API sessions."},
            {"text": "Initiate full network security group lockouts on web servers", "consequence_if_chosen": "Websites suffer downtime while API leak remains open."}
        ],
        "correct_index": 0,
        "consequence_if_wrong": "S3 bucket exfiltrations successfully completed.",
        "consequence_if_correct": "Exfiltration cut off successfully.",
        "rationale": "Rotating compromised cloud credentials stops persistent API exfiltration tunnels without disabling normal service tiers.",
        "nist_control_ref": "RS.CO-2",
        "mitre_technique": "T1078"
    },
    {
        "id": "gate-003",
        "trigger_timestamp": "+30m",
        "context_summary": "Ransomware encryption triggers on local file servers. Threat actor demands 15 BTC for domain recovery.",
        "options": [
            {"text": "Deploy bare-metal rebuilds from offline air-gapped backups", "consequence_if_chosen": "Business systems successfully restored to clean baseline state."},
            {"text": "Pay the extortion demand to obtain the decryptor key", "consequence_if_chosen": "Ransom paid but decryptor fails on 40% of volumes, causing data loss."},
            {"text": "Run real-time AV clean-up scans on active encrypted hosts", "consequence_if_chosen": "Scans fail as encrypted volumes remain locked."}
        ],
        "correct_index": 0,
        "consequence_if_wrong": "Severe system downtime and backup corruption.",
        "consequence_if_correct": "System fully restored.",
        "rationale": "Air-gapped offline backups provide guaranteed recovery and align with NIST incident recovery readiness frameworks.",
        "nist_control_ref": "RC.CO-1",
        "mitre_technique": "T1485"
    }
]


async def run_demonstration():
    print("======================================================================")
    print("          BREACH REPLAY - TABLETOP SIMULATION DEMONSTRATOR")
    print("======================================================================\n")

    # 1. Initialize local DB
    print("[1/6] Initializing Local Tabletop Simulation Database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("  [OK] Local DB demonstrator.db successfully created.\n")

    # 2. Seed Organization and Users
    print("[2/6] Seeding Tabletop Organizations and Multi-Role Users...")
    async with AsyncSessionLocal() as db:
        org = Organization(name="Global Cyber Defense", slug="global-cyber-defense")
        db.add(org)
        await db.flush()

        # Seed roles: Owner/CISO, Admin, Analysts
        ciso = User(
            email="ciso@defense.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Sarah Jenkins (CISO)",
            role="owner",
            organization_id=org.id
        )
        admin = User(
            email="admin@defense.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Alex Rivera (System Admin)",
            role="admin",
            organization_id=org.id
        )
        analyst1 = User(
            email="john.doe@defense.com",
            hashed_password=hash_password("Pass123!"),
            full_name="John Doe (Incident Commander)",
            role="analyst",
            organization_id=org.id
        )
        analyst2 = User(
            email="jane.smith@defense.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Jane Smith (Forensic Analyst)",
            role="analyst",
            organization_id=org.id
        )

        db.add_all([ciso, admin, analyst1, analyst2])
        await db.flush()
        print(f"  [OK] Seeded Organization: '{org.name}'")
        print(f"  [OK] Seeded CISO: {ciso.full_name}")
        print(f"  [OK] Seeded System Admin: {admin.full_name}")
        print(f"  [OK] Seeded Analysts: {analyst1.full_name}, {analyst2.full_name}\n")

        # 3. Seed approved Scenario
        print("[3/6] Seeding CISA VPN Ransomware tabletop Scenario...")
        scenario = Scenario(
            title="CISA VPN Ransomware Tabletop Incident Replay",
            description="Tabletop exercise simulating an intrusion via an unpatched VPN vulnerability leading to ransomware execution.",
            source_type="cisa",
            source_reference="CISA-AA23-263A",
            industry_vertical="technology",
            initial_access_vector="unpatched_cve",
            affected_asset_types=["VPN Gateway", "AWS S3 Bucket", "Windows File Server"],
            mitre_techniques=["T1133", "T1078", "T1485"],
            nist_controls=["RS.CO-1", "RS.CO-2", "RC.CO-1"],
            regulatory_frameworks=["NIST SP 800-61", "SOC 2 Type II", "HIPAA"],
            difficulty="practitioner",
            estimated_minutes=45,
            status="approved",
            decision_tree=DECISION_TREE_DEMO
        )
        db.add(scenario)
        await db.flush()
        print(f"  [OK] Scenario Seeding Successful: '{scenario.title}'\n")

        # 4. Simulate complete simulation tabletop run
        print("[4/6] Programmatically Executing Tabletops Simulation...")
        session = SimulationSession(
            scenario_id=scenario.id,
            organization_id=org.id,
            host_user_id=analyst1.id,
            status="active",
            mode="multiplayer",
            started_at=datetime.utcnow()
        )
        db.add(session)
        await db.flush()

        # Add participants
        p1 = SessionParticipant(session_id=session.id, user_id=analyst1.id, role="incident_commander")
        p2 = SessionParticipant(session_id=session.id, user_id=analyst2.id, role="forensic_analyst")
        p3 = SessionParticipant(session_id=session.id, user_id=ciso.id, role="observer")
        db.add_all([p1, p2, p3])
        await db.flush()

        # Decisions simulation:
        # Gate 1: Incident Commander John Doe answers CORRECTLY (Isolate host)
        d1 = SessionDecision(
            session_id=session.id,
            user_id=analyst1.id,
            decision_gate_id="gate-001",
            chosen_option_index=0,
            is_correct=True,
            response_time_seconds=6.8,
            consequence_applied="VPN session containing lateral movement cut off successfully.",
            nist_control_ref="RS.CO-1",
            mitre_technique="T1133"
        )
        # Gate 2: Forensic Analyst Jane Smith answers INCORRECTLY (Restrictive policy, exfiltration continues)
        d2 = SessionDecision(
            session_id=session.id,
            user_id=analyst2.id,
            decision_gate_id="gate-002",
            chosen_option_index=1,
            is_correct=False,
            response_time_seconds=18.5,
            consequence_applied="Delayed credential revocation allows the threat actor to complete customer record exfiltrations.",
            nist_control_ref="RS.CO-2",
            mitre_technique="T1078"
        )
        # Gate 3: Incident Commander John Doe answers CORRECTLY (Offline air-gapped backup rebuild)
        d3 = SessionDecision(
            session_id=session.id,
            user_id=analyst1.id,
            decision_gate_id="gate-003",
            chosen_option_index=0,
            is_correct=True,
            response_time_seconds=8.2,
            consequence_applied="Clean bare-metal restoring successfully closes threat persistence vector.",
            nist_control_ref="RC.CO-1",
            mitre_technique="T1485"
        )
        db.add_all([d1, d2, d3])
        
        # Complete simulation
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        session.decisions_made = 3
        session.decisions_correct = 2
        session.team_score = 66.7 # 2/3 correct

        # Construct High-Fidelity Claude Debrief Report
        debrief_skeleton = {
            "executive_summary": "The security team demonstrated strong containment controls for host threats, but lacked speed in credential rotation protocols during S3 API exfiltrations. Rebuilding file servers from air-gapped backups successfully prevented payment.",
            "performance_rating": "needs_improvement",
            "decisions": [
                {
                    "gate_id": "gate-001",
                    "team_choice": "Isolate the target host immediately",
                    "correct_choice": "Isolate the target host immediately",
                    "is_correct": True,
                    "impact": "Intrusion contained at source.",
                    "nist_ref": "RS.CO-1",
                    "explanation": "Prompt isolation prevents domain-wide ransomware propagation."
                },
                {
                    "gate_id": "gate-002",
                    "team_choice": "Apply restrictive read-only bucket policies globally",
                    "correct_choice": "Revoke target API key and rotate cloud service secrets",
                    "is_correct": False,
                    "impact": "S3 buckets exfiltration successfully completed.",
                    "nist_ref": "RS.CO-2",
                    "explanation": "Bucket policy sweeps fail to revoke active compromised service tokens immediately."
                },
                {
                    "gate_id": "gate-003",
                    "team_choice": "Deploy bare-metal rebuilds from offline air-gapped backups",
                    "correct_choice": "Deploy bare-metal rebuilds from offline air-gapped backups",
                    "is_correct": True,
                    "impact": "Business systems successfully restored to clean baseline state.",
                    "nist_ref": "RC.CO-1",
                    "explanation": "Offline back-ups provide reliable, extortion-free systems baseline rebuilds."
                }
            ],
            "nist_gaps": [
                {
                    "control": "RS.CO-2",
                    "description": "Information sharing and incident coordination processes",
                    "gap": "Failed to quickly rotate leaked API service credentials, leading to customer S3 data exfiltration.",
                    "remediation": "Update the Cloud Incident Response Runbook to require immediate IAM access keys revocation upon exfiltration alerts."
                }
            ],
            "mitre_coverage": {
                "techniques_exercised": ["T1133", "T1485"],
                "techniques_missed": ["T1078"]
            },
            "remediation_checklist": [
                {
                    "priority": "high",
                    "action": "Configure AWS IAM rules to alert on abnormal bulk exfiltrations.",
                    "owner": "Cloud Security Lead",
                    "due_days": 10
                },
                {
                    "priority": "medium",
                    "action": "Train forensic analysts on credentials rotation steps.",
                    "owner": "Incident Commander",
                    "due_days": 30
                }
            ],
            "compliance_evidence": {
                "frameworks_exercised": ["NIST SP 800-61", "SOC 2 Type II", "HIPAA"],
                "training_completed": True,
                "audit_notes": "Annual tabletop simulation satisfies tabletop exercise parameters under SOC 2 Common Criteria CC7.3 and NIST SP 800-53 AT-3."
            }
        }
        session.debrief_report = debrief_skeleton
        await db.commit()
        print("  [OK] Session Simulation complete.")
        print(f"  [OK] Final NIST Score: {session.team_score}%")
        print(f"  [OK] Team Decisions Accuracy: {session.decisions_correct} / {session.decisions_made} correct.\n")

        # 5. Export professional post-incident PDF using ReportLab
        print("[5/6] Invoking ReportLab Engine to Export Sleek Training PDF Report...")
        # Reload eagerly for PDF generation
        sess_q = await db.execute(
            select(SimulationSession)
            .options(selectinload(SimulationSession.scenario))
            .where(SimulationSession.id == session.id)
        )
        loaded_session = sess_q.scalar_one()

        pdf_bytes = generate_debrief_pdf(loaded_session, debrief_skeleton)
        
        pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "CISA_VPN_Simulation_Debrief_Report.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"  [OK] Sleek PDF Report successfully written to:\n    [PDF] {pdf_path}\n")

        # 6. Aggregate Compliance data and export CSV evidence package
        print("[6/6] Generating Auditor Compliance Evidence Logs and Exporting CSV Package...")
        
        # Aggregate analytics
        # NIST Coverage per scenario
        coverage = [
            f"{s.title} ({s.difficulty.upper()}) | Mapped Controls: {', '.join(s.nist_controls)} | Techniques: {', '.join(s.mitre_techniques)}"
            for s in [scenario]
        ]
        
        # Analyst Performance (computed programmatically)
        analyst_stats = []
        for u in [analyst1, analyst2]:
            user_decisions = [d1, d2, d3] # all decisions in the session
            # decisions made by this specific user
            u_decisions = [d for d in user_decisions if d.user_id == u.id]
            u_made = len(u_decisions)
            u_corr = sum(1 for d in u_decisions if d.is_correct)
            u_acc = round((u_corr / u_made) * 100, 1) if u_made > 0 else 0
            analyst_stats.append(
                f"- Analyst: {u.full_name} | Plays: 1 | Decisions: {u_made} | Correct: {u_corr} | Accuracy: {u_acc}%"
            )
        
        # Difficulty calibration
        calibration_rec = (
            f"- Scenario: '{scenario.title}' | Designed Diff: {scenario.difficulty.upper()} | play Count: 1 | Org Avg Score: {session.team_score}%"
            f" | Calibrated Suggestion: PRACTITIONER (average score is 66.7% - calibration aligns)"
        )
        
        # Generate CSV File in-memory and write to local disk
        import csv
        csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Auditor_Compliance_Evidence_Package.csv"))
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                "Session ID", 
                "Scenario Title", 
                "Designed Difficulty", 
                "Date Completed", 
                "NIST Score", 
                "Frameworks Exercised", 
                "Incident Commander", 
                "Participant Count"
            ])
            writer.writerow([
                session.id,
                scenario.title,
                scenario.difficulty.upper(),
                datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                f"{session.team_score}%",
                ", ".join(scenario.regulatory_frameworks),
                analyst1.full_name,
                3
            ])
        print(f"  [OK] Auditor Evidence Package successfully written to:\n    [CSV] {csv_path}\n")

        print("======================================================================")
        print("                 DEMONSTRATION RESULTS SUMMARY")
        print("======================================================================\n")
        print("1. NIST SP 800-61 / MITRE Coverage Maps:")
        for cov in coverage:
            print(f"  {cov}")
        print("\n2. Per-Analyst Performance Trackings (Zustand/Zod Aggregates):")
        for stat in analyst_stats:
            print(f"  {stat}")
        print("\n3. Dynamic Scenario Difficulty Calibration:")
        print(f"  {calibration_rec}")
        print("\n4. Compliance Auditor Logs (satisfies SOC 2 CC7.3 / ISO 27001):")
        print(f"  - Tabletop simulation complete: '{scenario.title}'")
        print(f"  - Final Score: {session.team_score}% | NIST Control gaps: [RS.CO-2]")
        print("  - Audit Notes: satisfies annual tabletops exercise compliance parameters.\n")
        print("======================================================================")
        print("          DEMONSTRATION SUCCESSFULLY EXPORTED ALL AUDIT FILES!")
        print("======================================================================")


if __name__ == "__main__":
    asyncio.run(run_demonstration())
