"""Leak-safety tests for the public Action Console run replay.

Mirrors test_arena_public_share.py's mint/404/label contract AND the
dossier-lock / fog-of-war unknown-tier discipline: a missing field is
the boundary, not a client blur. The public GET is unauthenticated, so
every extra key is a leak.

Covers:
  1. POST /action-runs/{id}/share — auth, owner-only, terminal row only
  2. GET  /action-runs/public/replay/{share_token} — no auth, locked DTO
  3. freeze_public_snapshot / build_public_replay_dto key locks
"""
import json
import uuid

import pytest

from app.models.action_run import ActionRun
from app.services import action_engine, verb_engine
from app.services.action_run_share import (
    PUBLIC_DTO_KEYS,
    PUBLIC_KNOWN_HOST_KEYS,
    PUBLIC_PLAYER_PLACEHOLDER,
    PUBLIC_TECHNIQUE_KEYS,
    PUBLIC_TIMELINE_KEYS,
    PUBLIC_UNKNOWN_HOST_KEYS,
    SHAREABLE_MODES,
    build_public_replay_dto,
    freeze_public_snapshot,
)
from app.services.action_run_store import action_run_store
from app.services.technique_dossier import TECHNIQUE_DOSSIER

pytestmark = pytest.mark.asyncio

# Distinctive values that must NEVER appear in a public response body —
# chosen so a coincidental integer (sequence_number, score) can't false-pass.
_LEAK_SEED = 42424241
_LEAK_IP = "203.0.113.99"
_LEAK_USERNAME = r"DOMAIN\jsmith_leak"
_LEAK_NARRATIVE = TECHNIQUE_DOSSIER["T1078"]["incident_narrative"]
_LEAK_SOURCE_REF = TECHNIQUE_DOSSIER["T1078"]["source_reference"]
_UNKNOWN_HOSTNAME = "SECRET-DC-01-LEAK"

# Keys that must not appear anywhere in the public JSON, nested included.
# Mirrors the dossier lock (incident_narrative/source_reference) and the
# fog-of-war unknown-tier check (hostname/role/... absent, not blurred).
#
# `target` is deliberately NOT in this set: MapEdge.to_dict uses
# {source, target} for host-id endpoints (NetworkMap's wire shape). Verb
# `target` (IP / username / party id) is stripped from the timeline and
# asserted per-entry below — a global ban would false-fail on the map.
FORBIDDEN_KEYS = frozenset({
    "seed",
    "hidden_iocs",
    "matches_on",
    "incident_narrative",
    "source_reference",
    "warranted",
    "rationale",
    "basis",
    "email",
    "full_name",
    "user_id",
    "unpatched_cves",
    "edr_installed",
    "raw_log",
    "forensics",
    "correct",
    "action_log",
    "score_breakdown",
    "revealed_iocs",
    "notified_party_ids",
    "collateral",
    "notifications",
    "action_run_id",
    "run_id",
})


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _all_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for v in obj.values():
            keys.update(_all_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_all_keys(item))
    return keys


def _poisoned_snapshot() -> dict:
    """A snapshot an attacker (or a sloppy freeze) might try to persist —
    extra keys on unknown/known hosts, full dossier fields on techniques,
    revealed_iocs with raw_log. The GET builder must strip all of it."""
    return {
        "hosts": [
            {
                "id": "unknown-1",
                "x": 80,
                "y": 60,
                "visibility": "unknown",
                "hostname": _UNKNOWN_HOSTNAME,
                "role": "domain_controller",
                "network_segment_id": "dc",
                "compromise_level": "domain_admin",
                "isolated": False,
                "unpatched_cves": ["CVE-2024-0001"],
                "edr_installed": False,
            },
            {
                "id": "known-1",
                "hostname": "CORP-WKS-22",
                "role": "workstation",
                "network_segment_id": "lan",
                "compromise_level": "foothold",
                "isolated": False,
                "x": 230,
                "y": 60,
                "unpatched_cves": ["CVE-2024-9999"],
                "edr_installed": True,
                "visibility": "known",
            },
        ],
        "edges": [{"source": "known-1", "target": "known-1", "kind": "secret"}],
        "techniques_encountered": [
            {
                "technique_id": "T1078",
                "name": TECHNIQUE_DOSSIER["T1078"]["name"],
                "description": TECHNIQUE_DOSSIER["T1078"]["description"],
                "incident_narrative": _LEAK_NARRATIVE,
                "source_reference": _LEAK_SOURCE_REF,
                "tactic": TECHNIQUE_DOSSIER["T1078"]["tactic"],
                "scenarios": TECHNIQUE_DOSSIER["T1078"]["scenarios"],
            }
        ],
        "revealed_iocs": [
            {
                "host_id": "known-1",
                "raw_log": f"connection from {_LEAK_IP}",
                "matches_on": {"ip": _LEAK_IP},
                "description": "hidden ioc leak",
            }
        ],
        "notified_party_ids": ["fbi"],
        "seed": _LEAK_SEED,
    }


def _poisoned_action_log() -> list[dict]:
    return [
        {
            "sequence_number": 0,
            "verb": "block_ip",
            "target": _LEAK_IP,
            "elapsed_seconds": 15,
            "cost": 15,
            "correct": True,
        },
        {
            "sequence_number": 1,
            "verb": "reset_creds",
            "target": _LEAK_USERNAME,
            "elapsed_seconds": 55,
            "cost": 40,
            "correct": False,
        },
        {
            "sequence_number": 2,
            "verb": "escalate",
            "target": "fbi",
            "elapsed_seconds": 55,
            "cost": 0,
            "warranted": True,
        },
    ]


async def _insert_completed_run(
    db,
    *,
    user_id,
    scenario_id,
    mode="scenario",
    share_token=None,
    public_snapshot=None,
    seed=_LEAK_SEED,
    action_log=None,
    score_breakdown=None,
    outcome="contained",
):
    run = ActionRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        scenario_id=scenario_id,
        seed=seed,
        mode=mode,
        action_log=action_log if action_log is not None else _poisoned_action_log(),
        score_breakdown=score_breakdown if score_breakdown is not None else {
            "total_score": 800,
            "score_pct": 80,
            "collateral": [{"host_id": "h-x", "hostname": "BACKUP-LEAK-01", "weight": 2}],
            "notifications": [
                {
                    "party_id": "fbi",
                    "party_name": "FBI",
                    "warranted": True,
                    "notified": True,
                    "rationale": "must never ship publicly",
                }
            ],
        },
        total_score=800,
        duration_seconds=90,
        outcome=outcome,
        share_token=share_token,
        public_snapshot=public_snapshot if public_snapshot is not None else _poisoned_snapshot(),
    )
    db.add(run)
    await db.flush()
    await db.commit()
    await db.refresh(run)
    return run


# ── freeze_public_snapshot (authenticated finalize path) ─────────────────────

async def test_freeze_public_snapshot_pre_scan_hosts_are_unknown_tier_only(approved_scenario):
    compiled = action_engine.compile_scenario(approved_scenario, seed=1)
    run = verb_engine.new_run(compiled)
    snapshot = freeze_public_snapshot(run)

    assert set(snapshot.keys()) == {"hosts", "edges", "techniques_encountered"}
    assert "revealed_iocs" not in snapshot
    assert "notified_party_ids" not in snapshot
    assert snapshot["hosts"], "compiled world should have hosts"
    for host in snapshot["hosts"]:
        assert set(host) == PUBLIC_UNKNOWN_HOST_KEYS, (
            f"unknown host carried extra keys: {set(host) - PUBLIC_UNKNOWN_HOST_KEYS}"
        )
        assert host["visibility"] == "unknown"
    assert snapshot["edges"] == []


async def test_freeze_public_snapshot_after_scan_known_hosts_have_no_forensics(approved_scenario):
    compiled = action_engine.compile_scenario(approved_scenario, seed=1)
    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "scan_network")
    snapshot = freeze_public_snapshot(result.run)

    assert snapshot["hosts"]
    for host in snapshot["hosts"]:
        assert set(host) <= PUBLIC_KNOWN_HOST_KEYS
        assert "visibility" not in host
        assert "unpatched_cves" not in host
        assert "edr_installed" not in host
        assert "hostname" in host


# ── build_public_replay_dto key lock (service-level, no HTTP) ────────────────

async def test_build_public_replay_dto_strips_poisoned_snapshot_and_action_log(
    db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    dto = build_public_replay_dto(run, "Colonial Pipeline Replay", PUBLIC_PLAYER_PLACEHOLDER)
    assert dto is not None
    assert set(dto.keys()) == PUBLIC_DTO_KEYS

    leaked = _all_keys(dto) & FORBIDDEN_KEYS
    assert leaked == set(), f"public DTO carried forbidden keys: {sorted(leaked)}"

    unknown = next(h for h in dto["hosts"] if h.get("visibility") == "unknown")
    assert set(unknown) == PUBLIC_UNKNOWN_HOST_KEYS

    known = next(h for h in dto["hosts"] if h.get("visibility") != "unknown")
    assert set(known) <= PUBLIC_KNOWN_HOST_KEYS
    assert "unpatched_cves" not in known

    for entry in dto["timeline"]:
        assert set(entry) == PUBLIC_TIMELINE_KEYS
        assert entry["verb"] in ("block_ip", "reset_creds", "escalate")

    for tech in dto["techniques_encountered"]:
        assert set(tech) == PUBLIC_TECHNIQUE_KEYS

    body = json.dumps(dto)
    assert _LEAK_IP not in body
    assert _LEAK_USERNAME not in body
    assert _UNKNOWN_HOSTNAME not in body
    assert _LEAK_NARRATIVE not in body
    assert _LEAK_SOURCE_REF not in body
    assert str(_LEAK_SEED) not in body
    assert "BACKUP-LEAK-01" not in body
    assert "must never ship publicly" not in body
    assert "CVE-2024-0001" not in body
    assert "CVE-2024-9999" not in body


async def test_build_public_replay_dto_returns_none_for_teaser_mode(
    db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id, mode="teaser",
    )
    assert "teaser" not in SHAREABLE_MODES
    assert build_public_replay_dto(run, "x", PUBLIC_PLAYER_PLACEHOLDER) is None


async def test_build_public_replay_dto_returns_none_without_snapshot(
    db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        public_snapshot=None,
    )
    # _insert treats None as "use default poison". Force a real NULL.
    run.public_snapshot = None
    await db.commit()
    await db.refresh(run)
    assert build_public_replay_dto(run, "x", PUBLIC_PLAYER_PLACEHOLDER) is None


# ── POST /action-runs/{id}/share ─────────────────────────────────────────────

async def test_share_404s_for_unknown_run_id(client, test_user):
    resp = await client.post(
        f"/api/v1/action-runs/{uuid.uuid4()}/share",
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Run not found"


async def test_share_404s_for_an_in_progress_live_run(client, test_user, approved_scenario):
    """A run that's still in the live store has no ActionRun row yet —
    mint must 404 (not 400 'still in progress', which would confirm the
    UUID is a live run)."""
    compiled = action_engine.compile_scenario(approved_scenario, seed=1)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(
        run_id, test_user["user"].id, approved_scenario.id, "scenario", compiled,
    )
    try:
        resp = await client.post(
            f"/api/v1/action-runs/{run_id}/share",
            headers=_auth_headers(test_user["token"]),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Run not found"
        assert await action_run_store.get(run_id) is not None  # still live
    finally:
        async with action_run_store._lock:
            action_run_store._runs.pop(run_id, None)


async def test_share_403s_for_another_users_completed_run(
    client, db, test_user, admin_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    resp = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(admin_user["token"]),
    )
    assert resp.status_code == 403


async def test_share_requires_authentication(client, db, test_user, approved_scenario):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    resp = await client.post(f"/api/v1/action-runs/{run.id}/share")
    assert resp.status_code == 403


async def test_share_404s_for_teaser_run_even_for_its_user(
    client, db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id, mode="teaser",
    )
    resp = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404


async def test_share_mints_idempotent_token_and_r_path(
    client, db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    first = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    assert first.status_code == 200
    token = first.json()["share_token"]
    assert token
    assert first.json()["share_url_path"] == f"/r/{token}"
    # Opaque — the run id must not be the token and must not be in the path.
    assert token != run.id
    assert run.id not in first.json()["share_url_path"]

    second = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    assert second.status_code == 200
    assert second.json()["share_token"] == token


# ── GET /action-runs/public/replay/{share_token} ─────────────────────────────

async def test_public_replay_404s_for_unknown_token(client):
    resp = await client.get("/api/v1/action-runs/public/replay/not-a-real-token")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Replay not found"
    # Empty-ish 404 body — no partial run state.
    assert set(resp.json().keys()) == {"detail"}


async def test_public_replay_404s_for_teaser_token_without_distinguishing_it(
    client, db, test_user, approved_scenario,
):
    token = "teaser-token-aaaaaaa"
    await _insert_completed_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="teaser",
        share_token=token,
    )
    resp = await client.get(f"/api/v1/action-runs/public/replay/{token}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Replay not found"


async def test_public_replay_404s_when_snapshot_is_missing(
    client, db, test_user, approved_scenario,
):
    token = "nosnap-token-bbbbbb"
    run = await _insert_completed_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        share_token=token,
        public_snapshot={},
    )
    run.public_snapshot = None
    await db.commit()
    resp = await client.get(f"/api/v1/action-runs/public/replay/{token}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Replay not found"


async def test_public_replay_requires_no_auth_and_locks_dto_keys(
    client, db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    mint = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    token = mint.json()["share_token"]

    resp = await client.get(f"/api/v1/action-runs/public/replay/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == PUBLIC_DTO_KEYS

    assert data["outcome"] == "contained"
    assert data["score"] == 800
    assert data["score_pct"] == 80
    assert data["duration_seconds"] == 90
    assert data["scenario_title"] == approved_scenario.title
    assert data["mode"] == "scenario"
    assert data["player_label"] == PUBLIC_PLAYER_PLACEHOLDER

    leaked = _all_keys(data) & FORBIDDEN_KEYS
    assert leaked == set(), f"public GET carried forbidden keys: {sorted(leaked)}"

    unknown = next(h for h in data["hosts"] if h.get("visibility") == "unknown")
    assert set(unknown) == verb_engine._UNKNOWN_HOST_FIELDS
    assert set(unknown) == PUBLIC_UNKNOWN_HOST_KEYS

    for tech in data["techniques_encountered"]:
        assert set(tech) == PUBLIC_TECHNIQUE_KEYS
        assert "incident_narrative" not in tech
        assert "source_reference" not in tech

    for entry in data["timeline"]:
        assert set(entry) <= PUBLIC_TIMELINE_KEYS
        assert "target" not in entry
        assert "warranted" not in entry
        assert "correct" not in entry

    body = resp.text
    assert test_user["user"].email not in body
    assert test_user["user"].full_name not in body
    assert test_user["user"].id not in body
    assert run.id not in body
    assert str(_LEAK_SEED) not in body
    assert _LEAK_IP not in body
    assert _LEAK_USERNAME not in body
    assert _UNKNOWN_HOSTNAME not in body
    assert _LEAK_NARRATIVE not in body
    assert _LEAK_SOURCE_REF not in body
    assert "BACKUP-LEAK-01" not in body
    assert "must never ship publicly" not in body
    assert "analyst@example.com" not in body


async def test_public_replay_label_shows_opted_in_handle(
    client, db, test_user, approved_scenario,
):
    test_user["user"].arena_profile_public = True
    test_user["user"].public_display_handle = "cyber_hero_1"
    db.add(test_user["user"])
    await db.commit()

    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    mint = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    resp = await client.get(
        f"/api/v1/action-runs/public/replay/{mint.json()['share_token']}"
    )
    assert resp.status_code == 200
    assert resp.json()["player_label"] == "cyber_hero_1"
    assert test_user["user"].email not in resp.text
    assert test_user["user"].full_name not in resp.text
    assert test_user["user"].id not in resp.text


async def test_public_replay_of_a_real_finalized_run_does_not_leak_seed(
    client, db, test_user, approved_scenario,
):
    """End-to-end through start_run/finalize — the path production uses —
    then mint + public GET. Seed from compile must not appear in the body."""
    compiled = action_engine.compile_scenario(approved_scenario, seed=_LEAK_SEED)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(
        run_id, test_user["user"].id, approved_scenario.id, "scenario", compiled,
    )
    try:
        applied = await action_run_store.apply_verb(run_id, "scan_network", None)
        assert applied is not None
        summary = await action_run_store.finalize(db, run_id)
        assert summary is not None
    finally:
        async with action_run_store._lock:
            action_run_store._runs.pop(run_id, None)

    mint = await client.post(
        f"/api/v1/action-runs/{run_id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    assert mint.status_code == 200
    resp = await client.get(
        f"/api/v1/action-runs/public/replay/{mint.json()['share_token']}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == PUBLIC_DTO_KEYS
    assert data["mode"] == "scenario"
    assert str(_LEAK_SEED) not in resp.text
    leaked = _all_keys(data) & FORBIDDEN_KEYS
    assert leaked == set(), f"finalized-run public GET leaked: {sorted(leaked)}"
    for host in data["hosts"]:
        if host.get("visibility") == "unknown":
            assert set(host) == verb_engine._UNKNOWN_HOST_FIELDS
        else:
            assert set(host) <= PUBLIC_KNOWN_HOST_KEYS
            assert "unpatched_cves" not in host
