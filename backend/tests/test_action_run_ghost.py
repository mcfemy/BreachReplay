"""Leak-safety + selection tests for Phase 4 ghost DTOs.

Mirrors test_action_run_public_share.py (PR #41) and the dossier lock
discipline (PR #34): a missing field is the boundary, not a client blur.
Ghost playback must NEVER be a raw action_log / state.delta passthrough
(spec §6 correction, PR #49).

Covers:
  1. Daily ghost DTO — no targets / warranted / correct / IOC / seed even
     from a poisoned action_log + score_breakdown
  2. Scenario ghost DTO — targets present; same judgment/hidden exclusions
  3. Selection — run just above on Daily leaderboard; non-terminal (live)
     runs cannot be selected; teaser / missing token 404
  4. HTTP: GET /daily/ghost (auth), GET /action-runs/public/ghost/{token}
"""
import json
import uuid
from datetime import date

import pytest

from app.models.action_run import ActionRun
from app.models.daily_challenge import DailyChallenge
from app.models.user import User
from app.services import action_engine, verb_engine
from app.services.action_run_ghost import (
    DAILY_GHOST_DTO_KEYS,
    GHOST_FORBIDDEN_KEYS,
    GHOST_MAP_FRAME_KEYS,
    PUBLIC_GHOST_DTO_KEYS,
    SCENARIO_TIMELINE_KEYS,
    build_ghost_dto,
    resolve_daily_ghost,
    resolve_ghost_by_share_token,
    select_daily_ghost_run,
)
from app.services.action_run_share import (
    PUBLIC_KNOWN_HOST_KEYS,
    PUBLIC_TIMELINE_KEYS,
    PUBLIC_UNKNOWN_HOST_KEYS,
    public_player_label,
)
from app.services.action_run_store import action_run_store
from app.services.technique_dossier import TECHNIQUE_DOSSIER

pytestmark = pytest.mark.asyncio

_LEAK_SEED = 42424241
_LEAK_IP = "203.0.113.99"
_LEAK_USERNAME = r"DOMAIN\jsmith_leak"
_LEAK_NARRATIVE = TECHNIQUE_DOSSIER["T1078"]["incident_narrative"]
_LEAK_SOURCE_REF = TECHNIQUE_DOSSIER["T1078"]["source_reference"]


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


def _poisoned_action_log() -> list[dict]:
    return [
        {
            "sequence_number": 0,
            "verb": "block_ip",
            "target": _LEAK_IP,
            "elapsed_seconds": 15,
            "cost": 15,
            "correct": True,
            "on_attack_path": True,
            "revealed_iocs": [{"raw_log": f"from {_LEAK_IP}", "matches_on": {"ip": _LEAK_IP}}],
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
            "rationale": "must never ship on ghost DTO",
        },
        {
            "sequence_number": 3,
            "verb": "scan_network",
            "target": None,
            "elapsed_seconds": 100,
            "cost": 45,
        },
    ]


def _poisoned_score_breakdown() -> dict:
    return {
        "total_score": 800,
        "score_pct": 80,
        "collateral": [{"host_id": "h-x", "hostname": "BACKUP-LEAK-01", "weight": 2}],
        "notifications": [
            {
                "party_id": "fbi",
                "party_name": "FBI",
                "warranted": True,
                "notified": True,
                "rationale": "must never ship on ghost DTO",
                "basis": "DFARS",
            }
        ],
        "seed": _LEAK_SEED,
        "revealed_iocs": [{"raw_log": "secret", "matches_on": {"ip": _LEAK_IP}}],
    }


async def _insert_run(
    db,
    *,
    user_id,
    scenario_id,
    mode="scenario",
    share_token=None,
    seed=_LEAK_SEED,
    action_log=None,
    score_breakdown=None,
    outcome="contained",
    total_score=800,
    duration_seconds=90,
    daily_challenge_id=None,
):
    run = ActionRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        scenario_id=scenario_id,
        daily_challenge_id=daily_challenge_id,
        seed=seed,
        mode=mode,
        action_log=action_log if action_log is not None else _poisoned_action_log(),
        score_breakdown=score_breakdown if score_breakdown is not None else _poisoned_score_breakdown(),
        total_score=total_score,
        duration_seconds=duration_seconds,
        outcome=outcome,
        share_token=share_token,
        public_snapshot={"hosts": [], "edges": [], "techniques_encountered": []},
    )
    db.add(run)
    await db.flush()
    await db.commit()
    await db.refresh(run)
    return run


async def _make_challenge(db, scenario_id: str, challenge_date: date) -> DailyChallenge:
    challenge = DailyChallenge(
        id=str(uuid.uuid4()),
        scenario_id=scenario_id,
        challenge_date=challenge_date,
        challenge_number=9000 + challenge_date.toordinal() % 1000,
        is_active=True,
        total_attempts=0,
    )
    db.add(challenge)
    await db.flush()
    await db.commit()
    await db.refresh(challenge)
    return challenge


# ── Service-level Daily DTO leak-safety ──────────────────────────────────────

async def test_daily_ghost_dto_strips_targets_and_judgment_from_poisoned_log(
    db, test_user, approved_scenario,
):
    run = await _insert_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id, mode="daily",
    )
    dto = build_ghost_dto(
        run,
        scenario=approved_scenario,
        player_label=public_player_label(test_user["user"]),
        include_targets=False,
        identity="ghost_run_id",
    )
    assert dto is not None
    assert set(dto.keys()) == DAILY_GHOST_DTO_KEYS
    assert dto["race_type"] == "daily"
    assert dto["ghost_run_id"] == run.id
    assert dto["containment_seconds"] == 90

    leaked = _all_keys(dto) & GHOST_FORBIDDEN_KEYS
    assert leaked == set(), f"Daily ghost DTO carried forbidden keys: {sorted(leaked)}"

    for entry in dto["verb_timeline"]:
        assert set(entry) <= PUBLIC_TIMELINE_KEYS
        assert "target" not in entry
        assert "warranted" not in entry
        assert "correct" not in entry
        assert "on_attack_path" not in entry

    for frame in dto["map_frames"]:
        assert set(frame.keys()) == GHOST_MAP_FRAME_KEYS
        for host in frame["hosts"]:
            if host.get("visibility") == "unknown":
                assert set(host) == PUBLIC_UNKNOWN_HOST_KEYS
            else:
                assert set(host) <= PUBLIC_KNOWN_HOST_KEYS

    body = json.dumps(dto)
    assert _LEAK_IP not in body
    assert _LEAK_USERNAME not in body
    assert "fbi" not in body  # escalate target party id
    assert str(_LEAK_SEED) not in body
    assert _LEAK_NARRATIVE not in body
    assert "must never ship on ghost DTO" not in body
    assert "BACKUP-LEAK-01" not in body


async def test_scenario_ghost_dto_includes_targets_but_not_judgment(
    db, test_user, approved_scenario,
):
    token = "scenarioGhostTok1"
    run = await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="scenario",
        share_token=token,
    )
    dto = build_ghost_dto(
        run,
        scenario=approved_scenario,
        player_label=public_player_label(test_user["user"]),
        include_targets=True,
        identity="share_token",
        share_token=token,
    )
    assert dto is not None
    assert set(dto.keys()) == PUBLIC_GHOST_DTO_KEYS
    assert dto["race_type"] == "scenario"
    assert dto["share_token"] == token
    assert "ghost_run_id" not in dto
    assert run.id not in json.dumps(dto)

    leaked = _all_keys(dto) & GHOST_FORBIDDEN_KEYS
    assert leaked == set(), f"Scenario ghost DTO carried forbidden keys: {sorted(leaked)}"

    targets = [e.get("target") for e in dto["verb_timeline"] if "target" in e]
    assert _LEAK_IP in targets
    assert _LEAK_USERNAME in targets
    assert "fbi" in targets

    for entry in dto["verb_timeline"]:
        assert set(entry) <= SCENARIO_TIMELINE_KEYS
        assert "warranted" not in entry
        assert "correct" not in entry
        assert "on_attack_path" not in entry
        assert "rationale" not in entry

    body = json.dumps(dto)
    assert str(_LEAK_SEED) not in body
    assert "must never ship on ghost DTO" not in body
    assert _LEAK_NARRATIVE not in body
    assert "BACKUP-LEAK-01" not in body


async def test_build_ghost_dto_rejects_teaser_mode(db, test_user, approved_scenario):
    run = await _insert_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id, mode="teaser",
    )
    assert build_ghost_dto(
        run,
        scenario=approved_scenario,
        player_label="x",
        include_targets=False,
        identity="ghost_run_id",
    ) is None


async def test_map_frames_advance_after_real_scan(db, test_user, approved_scenario):
    """Replay fidelity: scan_network lifts unknown → known on later frames."""
    compiled = action_engine.compile_scenario(approved_scenario, seed=7)
    run_state = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run_state, "scan_network")
    assert result.error is None
    action_log = list(result.run.action_log)

    run = await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="daily",
        seed=7,
        action_log=action_log,
        score_breakdown={"score_pct": 10, "total_score": 10},
        total_score=10,
        duration_seconds=45,
        outcome="breached",
    )
    dto = build_ghost_dto(
        run,
        scenario=approved_scenario,
        player_label="Responder",
        include_targets=False,
        identity="ghost_run_id",
    )
    assert dto is not None
    assert len(dto["map_frames"]) >= 2
    first = dto["map_frames"][0]
    last = dto["map_frames"][-1]
    assert all(h.get("visibility") == "unknown" for h in first["hosts"])
    assert all("hostname" in h for h in last["hosts"])
    assert dto["containment_seconds"] is None  # breached


# ── Selection ────────────────────────────────────────────────────────────────

async def test_select_daily_ghost_just_above_on_leaderboard(
    db, test_user, approved_scenario,
):
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 1))

    # Second user on the same org
    other = User(
        id=str(uuid.uuid4()),
        email=f"ghost-other-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Other Player",
        hashed_password="x",
        role="analyst",
        organization_id=test_user["user"].organization_id,
    )
    db.add(other)
    await db.flush()

    top = await _insert_run(
        db,
        user_id=other.id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=900,
        duration_seconds=60,
        seed=1,
        action_log=[{"sequence_number": 0, "verb": "scan_network", "target": None, "elapsed_seconds": 45, "cost": 45}],
        score_breakdown={"score_pct": 90},
    )
    me = await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=400,
        duration_seconds=120,
        seed=1,
        action_log=[],
        score_breakdown={"score_pct": 40},
    )

    ghost = await select_daily_ghost_run(
        db, daily_challenge_id=challenge.id, user_id=test_user["user"].id,
    )
    assert ghost is not None
    assert ghost.id == top.id
    assert ghost.id != me.id


async def test_select_daily_ghost_rank_one_has_nobody_above(
    db, test_user, approved_scenario,
):
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 2))
    await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=999,
        seed=1,
        action_log=[],
        score_breakdown={"score_pct": 99},
    )
    assert await select_daily_ghost_run(
        db, daily_challenge_id=challenge.id, user_id=test_user["user"].id,
    ) is None


async def test_select_daily_ghost_unranked_gets_last_place(
    db, test_user, approved_scenario,
):
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 3))
    other = User(
        id=str(uuid.uuid4()),
        email=f"ghost-last-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Last Place",
        hashed_password="x",
        role="analyst",
        organization_id=test_user["user"].organization_id,
    )
    db.add(other)
    await db.flush()
    last = await _insert_run(
        db,
        user_id=other.id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=50,
        seed=1,
        action_log=[],
        score_breakdown={"score_pct": 5},
    )
    ghost = await select_daily_ghost_run(
        db, daily_challenge_id=challenge.id, user_id=test_user["user"].id,
    )
    assert ghost is not None
    assert ghost.id == last.id


async def test_live_in_progress_run_cannot_be_selected_as_ghost(
    db, test_user, approved_scenario,
):
    """Non-terminal: live store only, no ActionRun row → selection misses it."""
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 4))
    compiled = action_engine.compile_scenario(approved_scenario, seed=3)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(
        run_id, test_user["user"].id, approved_scenario.id, "daily", compiled,
        daily_challenge_id=challenge.id,
    )
    try:
        ghost = await select_daily_ghost_run(
            db, daily_challenge_id=challenge.id, user_id="someone-else",
        )
        assert ghost is None
        dto = await resolve_daily_ghost(
            db, user_id="someone-else", daily_challenge_id=challenge.id,
        )
        assert dto is None
    finally:
        async with action_run_store._lock:
            action_run_store._runs.pop(run_id, None)


# ── HTTP ─────────────────────────────────────────────────────────────────────

async def test_http_public_scenario_ghost_includes_targets(
    client, db, test_user, approved_scenario,
):
    token = f"pubGhost{uuid.uuid4().hex[:10]}"
    await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="scenario",
        share_token=token,
    )
    resp = await client.get(f"/api/v1/action-runs/public/ghost/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == PUBLIC_GHOST_DTO_KEYS
    assert data["race_type"] == "scenario"
    assert any(e.get("target") == _LEAK_IP for e in data["verb_timeline"])
    leaked = _all_keys(data) & GHOST_FORBIDDEN_KEYS
    assert leaked == set()
    assert str(_LEAK_SEED) not in resp.text
    assert "warranted" not in resp.text


async def test_http_public_daily_ghost_via_token_strips_targets(
    client, db, test_user, approved_scenario,
):
    """A Daily share link still uses map-state-only (shared-seed bar)."""
    token = f"dailyGhost{uuid.uuid4().hex[:10]}"
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 5))
    await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="daily",
        share_token=token,
        daily_challenge_id=challenge.id,
        seed=1,
    )
    resp = await client.get(f"/api/v1/action-runs/public/ghost/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["race_type"] == "daily"
    assert data["share_token"] == token
    assert "ghost_run_id" not in data
    for entry in data["verb_timeline"]:
        assert "target" not in entry
    assert _LEAK_IP not in resp.text
    assert _LEAK_USERNAME not in resp.text


async def test_http_public_ghost_unknown_token_404(client):
    resp = await client.get("/api/v1/action-runs/public/ghost/not-a-real-token")
    assert resp.status_code == 404


async def test_http_daily_ghost_auth_and_selection(
    client, db, test_user, approved_scenario,
):
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 6))
    other = User(
        id=str(uuid.uuid4()),
        email=f"ghost-http-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Board Leader",
        hashed_password="x",
        role="analyst",
        organization_id=test_user["user"].organization_id,
    )
    db.add(other)
    await db.flush()
    top = await _insert_run(
        db,
        user_id=other.id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=700,
        seed=1,
        action_log=[{"sequence_number": 0, "verb": "scan_network", "target": None, "elapsed_seconds": 45, "cost": 45}],
        score_breakdown={"score_pct": 70},
    )
    await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="daily",
        daily_challenge_id=challenge.id,
        total_score=100,
        seed=1,
        action_log=[],
        score_breakdown={"score_pct": 10},
    )

    resp = await client.get(
        f"/api/v1/daily/ghost?daily_challenge_id={challenge.id}",
        headers=_auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == DAILY_GHOST_DTO_KEYS
    assert data["ghost_run_id"] == top.id
    assert data["race_type"] == "daily"
    for entry in data["verb_timeline"]:
        assert "target" not in entry
    leaked = _all_keys(data) & GHOST_FORBIDDEN_KEYS
    assert leaked == set()


async def test_http_daily_ghost_requires_auth(client, db, approved_scenario):
    challenge = await _make_challenge(db, approved_scenario.id, date(2031, 5, 7))
    resp = await client.get(f"/api/v1/daily/ghost?daily_challenge_id={challenge.id}")
    assert resp.status_code in (401, 403)


async def test_resolve_ghost_by_share_token_none_without_token_row(
    db, test_user, approved_scenario,
):
    run = await _insert_run(
        db,
        user_id=test_user["user"].id,
        scenario_id=approved_scenario.id,
        mode="scenario",
        share_token=None,
    )
    assert run.share_token is None
    assert await resolve_ghost_by_share_token(db, "nope") is None
