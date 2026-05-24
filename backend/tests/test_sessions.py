import pytest

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_session(client, test_user, approved_scenario):
    response = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["scenario_id"] == approved_scenario.id
    assert data["status"] == "waiting"
    assert data["host_user_id"] == test_user["user"].id


async def test_create_session_no_scenario(client, test_user):
    response = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": "fake-scenario-id", "mode": "solo"},
    )
    assert response.status_code == 404


async def test_start_session(client, test_user, approved_scenario):
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    session_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/sessions/{session_id}/start",
        headers=auth_headers(test_user["token"]),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["started_at"] is not None


async def test_submit_decision(client, test_user, approved_scenario):
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    session_id = create_resp.json()["id"]
    await client.post(
        f"/api/v1/sessions/{session_id}/start",
        headers=auth_headers(test_user["token"]),
    )

    response = await client.post(
        f"/api/v1/sessions/{session_id}/decisions",
        headers=auth_headers(test_user["token"]),
        json={
            "decision_gate_id": "gate-001",
            "chosen_option_index": 0,
            "response_time_seconds": 12.5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision_gate_id"] == "gate-001"
    assert data["is_correct"] is True


async def test_complete_session(client, test_user, approved_scenario):
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "solo"},
    )
    session_id = create_resp.json()["id"]
    await client.post(
        f"/api/v1/sessions/{session_id}/start",
        headers=auth_headers(test_user["token"]),
    )
    await client.post(
        f"/api/v1/sessions/{session_id}/decisions",
        headers=auth_headers(test_user["token"]),
        json={
            "decision_gate_id": "gate-001",
            "chosen_option_index": 0,
            "response_time_seconds": 8.0,
        },
    )

    response = await client.post(
        f"/api/v1/sessions/{session_id}/complete",
        headers=auth_headers(test_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["team_score"] == 100.0
    assert data["decisions_made"] == 1
    assert data["decisions_correct"] == 1


async def test_get_session_not_found(client, test_user):
    response = await client.get("/api/v1/sessions/fake-id", headers=auth_headers(test_user["token"]))
    assert response.status_code == 404
