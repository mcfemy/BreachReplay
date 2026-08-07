"""Tests for POST /action-runs (Phase 2, Item 3) — the REST endpoint that
mints a run_id and registers it live in action_run_store before the client
connects to /ws/run/{run_id}."""
import pytest

from app.services.action_run_store import action_run_store

pytestmark = pytest.mark.asyncio


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_action_run_for_an_approved_scenario(client, test_user, approved_scenario):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": approved_scenario.id},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scenario_id"] == approved_scenario.id
    assert body["mode"] == "scenario"
    assert body["cap_seconds"] == 600
    assert isinstance(body["seed"], int)
    # A real gap found end-to-end on breachreplay.com: the WS run_id and
    # the eventual persisted ActionRun.id used to be two different,
    # independently-generated values, with no hint in this response that
    # a second id even existed — a caller (a real frontend, or a script)
    # that reused run_id for later designation got a confusing "run not
    # found". action_run_store.finalize() now persists the row under this
    # exact id, so it can be returned here, honestly, up front.
    assert body["action_run_id"] == body["run_id"]

    live = await action_run_store.get(body["run_id"])
    assert live is not None
    assert live.user_id == test_user["user"].id
    assert live.run_state.elapsed_seconds == 0

    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)


async def test_create_action_run_requires_authentication(client, approved_scenario):
    resp = await client.post("/api/v1/action-runs", json={"scenario_id": approved_scenario.id})
    assert resp.status_code == 403


async def test_create_action_run_404s_for_an_unknown_scenario(client, test_user):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": "not-a-real-scenario-id"},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404


async def test_create_action_run_404s_for_a_non_approved_scenario(client, db, test_user):
    from app.models.scenario import Scenario

    draft = Scenario(
        title="Draft Scenario",
        source_type="manual",
        source_reference="TEST-DRAFT-001",
        difficulty="practitioner",
        status="draft",
        decision_tree=[],
        alert_sequence=[],
    )
    db.add(draft)
    await db.flush()

    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": draft.id},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404
