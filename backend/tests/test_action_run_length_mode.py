"""Action Console Compressed vs Full length mode (cap + compression_ratio)."""
import pytest
from sqlalchemy import select

from app.models.action_run import ActionRun
from app.models.scenario import Scenario
from app.services import action_engine
from app.services.action_run_store import (
    CAP_SECONDS_BY_MODE,
    LENGTH_COMPRESSED,
    LENGTH_FULL,
    action_run_store,
    resolve_scenario_length_params,
)

pytestmark = pytest.mark.asyncio

# Mirrors Colonial-shaped pacing used by test_action_engine compression tests:
# authored +49m final gate compresses to 367s at ratio 8.0, stays 2940s at 1.0.
_LONG_DECISION_TREE = [
    {
        "id": "gate-001",
        "trigger_timestamp": "+4m",
        "mitre_technique": "T1078",
        "context_summary": "Early foothold.",
        "options": [],
        "correct_index": 0,
        "consequence_if_wrong": "Missed.",
        "rationale": "Act.",
        "nist_control_ref": "DE.AE-2",
    },
    {
        "id": "gate-012",
        "trigger_timestamp": "+49m",
        "mitre_technique": "T1486",
        "context_summary": "Terminal impact.",
        "options": [],
        "correct_index": 0,
        "consequence_if_wrong": "Breached.",
        "rationale": "Contain.",
        "nist_control_ref": "RS.MI-2",
    },
]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def compressible_scenario(db):
    scenario = Scenario(
        title="Length Mode Colonial-shaped",
        source_type="manual",
        source_reference="TEST-LENGTH-001",
        difficulty="practitioner",
        industry_vertical="energy",
        status="approved",
        estimated_minutes=45,
        compression_ratio=8.0,
        decision_tree=_LONG_DECISION_TREE,
        alert_sequence=[
            {
                "timestamp": "+8m",
                "severity": "high",
                "source_system": "SIEM",
                "rule_id": "RULE-LEN",
                "description": "Lateral movement",
                "raw_log": "src=MAIL-01",
            }
        ],
    )
    db.add(scenario)
    await db.flush()
    return scenario


def test_resolve_scenario_length_params_compressed_and_full():
    mode, cap, override = resolve_scenario_length_params("compressed", 45)
    assert mode == LENGTH_COMPRESSED
    assert cap == 600
    assert override is None

    mode, cap, override = resolve_scenario_length_params("full", 45)
    assert mode == LENGTH_FULL
    assert cap == 45 * 60
    assert override == 1.0

    mode, cap, override = resolve_scenario_length_params("full", None)
    assert cap == 45 * 60


async def test_create_defaults_to_compressed_600_and_scenario_ratio(
    client, test_user, compressible_scenario,
):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": compressible_scenario.id},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["length"] == "compressed"
    assert body["cap_seconds"] == 600

    live = await action_run_store.get(body["run_id"])
    assert live is not None
    assert live.cap_seconds == 600
    assert live.length_mode == LENGTH_COMPRESSED
    assert live.compression_ratio == 8.0
    final = next(s for s in live.run_state.compiled.stages if s.is_final)
    assert final.trigger_seconds == 2940 // 8  # 367

    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)


async def test_create_full_uses_uncompressed_timeline_and_estimated_cap(
    client, test_user, compressible_scenario,
):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": compressible_scenario.id, "length": "full"},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["length"] == "full"
    assert body["cap_seconds"] == 45 * 60

    live = await action_run_store.get(body["run_id"])
    assert live is not None
    assert live.cap_seconds == 2700
    assert live.length_mode == LENGTH_FULL
    assert live.compression_ratio == 1.0
    final = next(s for s in live.run_state.compiled.stages if s.is_final)
    assert final.trigger_seconds == 49 * 60  # uncompressed
    by_ts = {a["timestamp"]: a["trigger_seconds"] for a in live.run_state.compiled.alert_lines}
    assert by_ts["+8m"] == 8 * 60

    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)


async def test_finalize_persists_length_mode_cap_and_ratio(
    client, db, test_user, compressible_scenario,
):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": compressible_scenario.id, "length": "full"},
        headers=_auth_headers(test_user["token"]),
    )
    run_id = resp.json()["run_id"]

    summary = await action_run_store.finalize(db, run_id, forced_outcome="breached")
    assert summary is not None

    row = await db.scalar(select(ActionRun).where(ActionRun.id == run_id))
    assert row is not None
    assert row.length_mode == LENGTH_FULL
    assert row.cap_seconds == 2700
    assert row.compression_ratio == 1.0


async def test_compressed_explicit_matches_default(client, test_user, compressible_scenario):
    resp = await client.post(
        "/api/v1/action-runs",
        json={"scenario_id": compressible_scenario.id, "length": "compressed"},
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["cap_seconds"] == CAP_SECONDS_BY_MODE["scenario"]
    assert body["length"] == "compressed"

    async with action_run_store._lock:
        action_run_store._runs.pop(body["run_id"], None)


def test_compile_scenario_ratio_override_is_independent_of_scenario_field():
    scenario = {
        "id": "dict-scn",
        "industry_vertical": "energy",
        "compression_ratio": 8.0,
        "decision_tree": _LONG_DECISION_TREE,
        "alert_sequence": [],
        "hidden_iocs": [],
        "pressure_injections": [],
    }
    compressed = action_engine.compile_scenario(scenario, seed=7)
    full = action_engine.compile_scenario(scenario, seed=7, compression_ratio=1.0)
    c_final = next(s for s in compressed.stages if s.is_final)
    f_final = next(s for s in full.stages if s.is_final)
    assert c_final.trigger_seconds == 2940 // 8
    assert f_final.trigger_seconds == 2940
