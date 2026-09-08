import pytest

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_list_scenarios_authenticated(client, test_user, approved_scenario):
    response = await client.get("/api/v1/scenarios", headers=auth_headers(test_user["token"]))
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(s["id"] == approved_scenario.id for s in data)


async def test_list_scenarios_unauthenticated(client):
    response = await client.get("/api/v1/scenarios")
    assert response.status_code == 403


async def test_get_scenario(client, test_user, approved_scenario):
    response = await client.get(
        f"/api/v1/scenarios/{approved_scenario.id}",
        headers=auth_headers(test_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == approved_scenario.id
    assert data["title"] == approved_scenario.title
    assert data["decision_tree"] == approved_scenario.decision_tree


async def test_get_scenario_not_found(client, test_user):
    response = await client.get("/api/v1/scenarios/nonexistent-id", headers=auth_headers(test_user["token"]))
    assert response.status_code == 404


async def test_create_scenario_admin(client, admin_user):
    response = await client.post(
        "/api/v1/scenarios",
        headers=auth_headers(admin_user["token"]),
        json={
            "title": "Admin Created Scenario",
            "source_type": "manual",
            "difficulty": "practitioner",
        },
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Admin Created Scenario"


async def test_create_scenario_non_admin(client, test_user):
    response = await client.post(
        "/api/v1/scenarios",
        headers=auth_headers(test_user["token"]),
        json={
            "title": "Non Admin Scenario",
            "source_type": "manual",
            "difficulty": "practitioner",
        },
    )
    assert response.status_code == 403


async def test_list_and_get_include_real_world_stakes(client, test_user, db):
    """Library case-file field must round-trip through list + detail APIs."""
    from app.models.scenario import Scenario

    stakes = "$4.4M ransom paid. 45% of East Coast fuel supply, shut down for days."
    scenario = Scenario(
        title="Colonial Pipeline Ransomware Attack",
        description="Test description for library card.",
        real_world_stakes=stakes,
        source_type="manual",
        source_reference="CISA-AA21-131A",
        difficulty="expert",
        status="approved",
        is_private=False,
        # list_scenarios filters out empty alert_sequence — match library shape.
        alert_sequence=[
            {
                "timestamp": "+0m",
                "severity": "critical",
                "source_system": "SIEM",
                "rule_id": "RULE-001",
                "description": "Unusual VPN login",
            }
        ],
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)

    list_resp = await client.get("/api/v1/scenarios", headers=auth_headers(test_user["token"]))
    assert list_resp.status_code == 200
    listed = next(s for s in list_resp.json() if s["id"] == scenario.id)
    assert listed["real_world_stakes"] == stakes
    assert listed["source_reference"] == "CISA-AA21-131A"
    assert listed["description"] == "Test description for library card."

    detail_resp = await client.get(
        f"/api/v1/scenarios/{scenario.id}",
        headers=auth_headers(test_user["token"]),
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["real_world_stakes"] == stakes
    assert detail["source_reference"] == "CISA-AA21-131A"
