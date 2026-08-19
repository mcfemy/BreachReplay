"""
Tests for the Technique Dossier's read side: app.services.dossier_service
(pure query-time aggregation over TechniqueEncounter) and GET /dossier/me
(app/api/routes/dossier.py). The write side (encountered_technique_ids
tracking in verb_engine, persistence in action_run_store.finalize) is
covered separately in test_verb_engine.py and test_action_run_store.py.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.technique_encounter import TechniqueEncounter
from app.services import dossier_service
from app.services.technique_dossier import TECHNIQUE_DOSSIER

pytestmark = pytest.mark.asyncio


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_compute_user_dossier_returns_every_technique_unencountered_for_a_fresh_user(db, test_user):
    dossier = await dossier_service.compute_user_dossier(db, test_user["user"].id)

    assert dossier["total_techniques"] == len(TECHNIQUE_DOSSIER) == 30
    assert dossier["encountered_count"] == 0
    assert set(dossier["techniques"].keys()) == set(TECHNIQUE_DOSSIER.keys())
    for technique_id, entry in dossier["techniques"].items():
        assert entry["encountered"] is False
        assert entry["encounter_count"] == 0
        assert entry["first_encountered_at"] is None
        assert entry["last_encountered_at"] is None
        # Static reference content (name/description) stays visible for browsing
        # even when locked, joined against the static content not just the rollup row.
        assert entry["name"] == TECHNIQUE_DOSSIER[technique_id]["name"]
        assert entry["tactic"] == TECHNIQUE_DOSSIER[technique_id]["tactic"]
        assert entry["description"] == TECHNIQUE_DOSSIER[technique_id]["description"]
        # But the real narrative content is withheld server-side, not just
        # hidden client-side, so the lock is an actual data boundary.
        assert entry["incident_narrative"] is None
        assert entry["source_reference"] is None


async def test_compute_user_dossier_reflects_a_real_encounter_row(db, test_user):
    now = datetime.utcnow()
    db.add(TechniqueEncounter(
        user_id=test_user["user"].id, technique_id="T1078",
        encounter_count=3, first_encountered_at=now, last_encountered_at=now,
    ))
    await db.flush()

    dossier = await dossier_service.compute_user_dossier(db, test_user["user"].id)

    assert dossier["encountered_count"] == 1
    entry = dossier["techniques"]["T1078"]
    assert entry["encountered"] is True
    assert entry["encounter_count"] == 3
    assert entry["first_encountered_at"] is not None
    assert entry["last_encountered_at"] is not None

    # Every other technique in the dossier is still present, still unencountered.
    other = dossier["techniques"]["T1003"]
    assert other["encountered"] is False
    assert other["encounter_count"] == 0


async def test_compute_user_dossier_withholds_narrative_and_source_only_for_unencountered_techniques(db, test_user):
    """The frontend blurs locked names client-side, but that's cosmetic — the
    API itself must not ship incident_narrative/source_reference for
    techniques the user hasn't encountered, or the lock isn't a real data
    boundary."""
    now = datetime.utcnow()
    db.add(TechniqueEncounter(
        user_id=test_user["user"].id, technique_id="T1078",
        encounter_count=1, first_encountered_at=now, last_encountered_at=now,
    ))
    await db.flush()

    dossier = await dossier_service.compute_user_dossier(db, test_user["user"].id)

    encountered = dossier["techniques"]["T1078"]
    assert encountered["incident_narrative"] == TECHNIQUE_DOSSIER["T1078"]["incident_narrative"]
    assert encountered["source_reference"] == TECHNIQUE_DOSSIER["T1078"]["source_reference"]

    unencountered = dossier["techniques"]["T1003"]
    assert unencountered["incident_narrative"] is None
    assert unencountered["source_reference"] is None
    # Static reference content is still present for browsing.
    assert unencountered["name"] == TECHNIQUE_DOSSIER["T1003"]["name"]
    assert unencountered["description"] == TECHNIQUE_DOSSIER["T1003"]["description"]


async def test_compute_user_dossier_scopes_encounters_to_the_requesting_user(db, test_user, test_org):
    from app.core.security import hash_password
    from app.models.user import User

    other_user = User(
        email="other-analyst@example.com", hashed_password=hash_password("StrongPass1!"),
        full_name="Other Analyst", role="analyst", organization_id=test_org.id,
    )
    db.add(other_user)
    await db.flush()

    now = datetime.utcnow()
    db.add(TechniqueEncounter(
        user_id=other_user.id, technique_id="T1078",
        encounter_count=1, first_encountered_at=now, last_encountered_at=now,
    ))
    await db.flush()

    dossier = await dossier_service.compute_user_dossier(db, test_user["user"].id)
    assert dossier["encountered_count"] == 0
    assert dossier["techniques"]["T1078"]["encountered"] is False


async def test_get_my_dossier_requires_authentication(client):
    resp = await client.get("/api/v1/dossier/me")
    assert resp.status_code == 403


async def test_get_my_dossier_returns_the_full_dossier_for_an_authenticated_user(client, test_user):
    resp = await client.get("/api/v1/dossier/me", headers=_auth_headers(test_user["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_techniques"] == 30
    assert body["encountered_count"] == 0
    assert len(body["techniques"]) == 30
    # No incident_narrative/source_reference leaks over the wire for a
    # fresh user with zero encounters.
    for entry in body["techniques"].values():
        assert entry["incident_narrative"] is None
        assert entry["source_reference"] is None


async def test_get_my_dossier_reflects_encounters_persisted_through_a_real_action_run(client, db, test_user):
    """End-to-end across the write/read boundary: play a real Action Console
    run through action_run_store, finalize it (persisting a
    TechniqueEncounter row via the real write path, not a hand-inserted
    fixture row), then confirm GET /dossier/me picks it up."""
    from app.models.scenario import Scenario
    from app.services import action_engine
    from app.services.action_run_store import ActionRunStore

    decision_tree = [
        {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
         "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
         "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
    ]
    scenario = Scenario(
        title="Dossier E2E Test Scenario", source_type="manual", source_reference="TEST-DOSSIER-001",
        difficulty="practitioner", status="approved", decision_tree=decision_tree,
        compression_ratio=1.0, alert_sequence=[],
    )
    db.add(scenario)
    await db.flush()

    compiled = action_engine.compile_scenario(scenario, seed=1)
    store = ActionRunStore()
    run_id = "dossier-e2e-run-1"
    await store.start_run(run_id, test_user["user"].id, scenario.id, "scenario", compiled)

    is_over = False
    while not is_over:
        result, is_over = await store.apply_verb(run_id, "scan_network", None)
        assert result.error is None

    await store.finalize(db, run_id)

    resp = await client.get("/api/v1/dossier/me", headers=_auth_headers(test_user["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["encountered_count"] == 1
    assert body["techniques"]["T1078"]["encountered"] is True
    assert body["techniques"]["T1078"]["encounter_count"] == 1
    assert body["techniques"]["T1078"]["incident_narrative"] == TECHNIQUE_DOSSIER["T1078"]["incident_narrative"]
    assert body["techniques"]["T1078"]["source_reference"] == TECHNIQUE_DOSSIER["T1078"]["source_reference"]
