import pytest
from sqlalchemy import select
from app.models.session import SimulationSession, SessionParticipant


pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_debrief_pdf_export_success(client, test_user, approved_scenario, db):
    """Test that a completed session with a debrief report correctly returns a formatted ReportLab PDF stream."""
    # 1. Create a session
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # 2. Start session
    await client.post(
        f"/api/v1/sessions/{session_id}/start",
        headers=auth_headers(test_user["token"]),
    )

    # 3. Complete session
    complete_resp = await client.post(
        f"/api/v1/sessions/{session_id}/complete",
        headers=auth_headers(test_user["token"]),
    )
    assert complete_resp.status_code == 200

    # 4. Inject mock debrief_report directly into database session (Celery task is mocked in conftest)
    result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
    session = result.scalar_one_or_none()
    assert session is not None

    session.debrief_report = {
        "executive_summary": "Test executive summary detailing simulated incident response capabilities.",
        "performance_rating": "excellent",
        "decisions": [
            {
                "gate_id": "gate-001",
                "team_choice": "Isolate host",
                "correct_choice": "Isolate host",
                "is_correct": True,
                "impact": "Good Containment.",
                "nist_ref": "RS.CO-1",
                "explanation": "Isolating infected endpoints contains active lateral threats."
            }
        ],
        "nist_gaps": [],
        "mitre_coverage": {
            "techniques_exercised": ["T1021"],
            "techniques_missed": []
        },
        "remediation_checklist": [
            {
                "priority": "high",
                "action": "Ensure all SOC analysts review lateral movement containment.",
                "owner": "SOC Lead",
                "due_days": 15
            }
        ],
        "compliance_evidence": {
            "frameworks_exercised": ["NIST SP 800-61", "ISO 27001"],
            "training_completed": True,
            "audit_notes": "Tabletop exercise satisfies annual tabletop requirements."
        }
    }
    await db.commit()

    # 5. Call get PDF route
    pdf_resp = await client.get(
        f"/api/v1/sessions/{session_id}/debrief/pdf",
        headers=auth_headers(test_user["token"]),
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert f"attachment; filename=BreachReplay_Debrief_{session_id}.pdf" in pdf_resp.headers["content-disposition"]
    assert len(pdf_resp.content) > 1000  # valid PDF generated


async def test_debrief_pdf_export_not_completed_fails(client, test_user, approved_scenario):
    """Test that requesting PDF export of a non-completed session raises an error."""
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    session_id = create_resp.json()["id"]

    pdf_resp = await client.get(
        f"/api/v1/sessions/{session_id}/debrief/pdf",
        headers=auth_headers(test_user["token"]),
    )
    assert pdf_resp.status_code == 400
    assert "Session not yet completed" in pdf_resp.json()["detail"]


async def test_compliance_analytics_as_admin(client, admin_user, approved_scenario, db):
    """Test that an organization administrator can successfully access aggregated compliance metrics."""
    # Create a completed session with a participant record so the analytics aggregate correctly
    sess = SimulationSession(
        scenario_id=approved_scenario.id,
        organization_id=admin_user["user"].organization_id,
        host_user_id=admin_user["user"].id,
        status="completed",
        team_score=90.0,
        decisions_made=1,
        decisions_correct=1,
        debrief_report={
            "executive_summary": "Test executive summary",
            "performance_rating": "good",
            "decisions": [],
            "nist_gaps": [],
            "mitre_coverage": {"techniques_exercised": [], "techniques_missed": []},
            "remediation_checklist": [],
            "compliance_evidence": {"frameworks_exercised": ["HIPAA"]}
        }
    )
    db.add(sess)
    await db.flush()

    # The analytics endpoint resolves analyst sessions via SessionParticipant, not host_user_id.
    # Without this record the admin user would show sessions_completed=0.
    participant = SessionParticipant(
        session_id=sess.id,
        user_id=admin_user["user"].id,
        role="incident_commander",
    )
    db.add(participant)
    await db.commit()

    response = await client.get(
        "/api/v1/admin/compliance-analytics",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    assert "scenario_coverage" in data
    assert "analyst_performance" in data
    assert "calibrations" in data
    assert "compliance_evidence" in data

    # Verify scenario coverage
    assert len(data["scenario_coverage"]) >= 1
    assert data["scenario_coverage"][0]["title"] == approved_scenario.title

    # Verify analyst performance shows the admin user WITH the completed session
    admin_stats = next(
        (a for a in data["analyst_performance"] if a["user_id"] == admin_user["user"].id),
        None,
    )
    assert admin_stats is not None
    assert admin_stats["sessions_completed"] >= 1


async def test_compliance_analytics_as_non_admin_blocked(client, test_user):
    """Test that non-admin analysts are restricted from viewing organization-wide compliance details."""
    response = await client.get(
        "/api/v1/admin/compliance-analytics",
        headers=auth_headers(test_user["token"]),
    )
    assert response.status_code == 403


async def test_compliance_evidence_csv_export(client, admin_user, approved_scenario, db):
    """Test that compliance logs are successfully exported in CSV format for auditors."""
    sess = SimulationSession(
        scenario_id=approved_scenario.id,
        organization_id=admin_user["user"].organization_id,
        host_user_id=admin_user["user"].id,
        status="completed",
        team_score=85.5,
        decisions_made=1,
        decisions_correct=1,
    )
    db.add(sess)
    await db.commit()

    response = await client.get(
        "/api/v1/admin/compliance-evidence/export",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=BreachReplay_Compliance_Evidence.csv" in response.headers["content-disposition"]
    
    csv_content = response.content.decode("utf-8")
    assert "Session ID,Scenario Title,Designed Difficulty,Date Completed,NIST Score,Frameworks Exercised,Incident Commander ID,Participant Count" in csv_content
    assert approved_scenario.title in csv_content
    assert "85.5%" in csv_content
