import pytest

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_list_scenarios_authenticated(client, test_user):
    response = await client.get("/api/v1/scenarios", headers=auth_headers(test_user["token"]))
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_list_scenarios_unauthenticated(client):
    response = await client.get("/api/v1/scenarios")
    assert response.status_code == 403


async def test_get_scenario_not_found(client, test_user):
    response = await client.get("/api/v1/scenarios/nonexistent-id", headers=auth_headers(test_user["token"]))
    assert response.status_code == 404


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
