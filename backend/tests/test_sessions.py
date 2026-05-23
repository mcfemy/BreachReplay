import pytest

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_session_no_scenario(client, test_user):
    response = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": "fake-scenario-id", "mode": "solo"},
    )
    assert response.status_code == 404


async def test_get_session_not_found(client, test_user):
    response = await client.get("/api/v1/sessions/fake-id", headers=auth_headers(test_user["token"]))
    assert response.status_code == 404
