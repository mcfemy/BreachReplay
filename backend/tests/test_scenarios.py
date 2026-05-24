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
