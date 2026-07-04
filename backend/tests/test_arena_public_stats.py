"""Tests for Live Breach Events Phase 3: public aggregate stats
("Global Incident Response Index").

Covers two no-auth routes:
  1. GET /arena/public/stats/global-index        — per-archetype_key
     containment/attacker-win rate + avg resolution time from ArenaMatch,
     plus an `overall` aggregate bucket.
  2. GET /scenarios/public/stats/{scenario_id}    — per-scenario "success
     rate" from SimulationSession.

Both endpoints are backed by a module-level app.core.stats_cache.TTLCache
instance that persists for the whole pytest session (it's created once at
import time) — every test that depends on fresh data clears the relevant
cache first via the `clear_stats_caches` autouse fixture below, mirroring
how test_arena_public_share.py builds fixtures directly against the `db`
fixture.
"""
import uuid
from datetime import datetime, timedelta

import pytest

from app.api.routes.arena import _GLOBAL_INDEX_CACHE
from app.api.routes.scenarios import _SCENARIO_STATS_CACHE
from app.models.arena import ArenaMatch
from app.models.scenario import Scenario
from app.models.session import SimulationSession

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_stats_caches():
    """Both stats caches are module-level singletons that outlive any single
    test — clear them before and after every test so one test's fixture
    data can never leak into another's cached response."""
    _GLOBAL_INDEX_CACHE.clear()
    _SCENARIO_STATS_CACHE.clear()
    yield
    _GLOBAL_INDEX_CACHE.clear()
    _SCENARIO_STATS_CACHE.clear()


def _make_match(
    db,
    archetype_key="small_healthcare",
    status="defender_won",
    started_at=None,
    completed_at=None,
    seed=1,
) -> ArenaMatch:
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=archetype_key,
        mode="human_defends_vs_ai",
        status=status,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(match)
    return match


def _make_session(db, scenario_id, host_user_id, decisions_made, decisions_correct, status="completed", team_score=None) -> SimulationSession:
    sess = SimulationSession(
        scenario_id=scenario_id,
        host_user_id=host_user_id,
        status=status,
        team_score=team_score,
        decisions_made=decisions_made,
        decisions_correct=decisions_correct,
    )
    db.add(sess)
    return sess


# ── GET /arena/public/stats/global-index ────────────────────────────────────

async def test_global_index_reachable_without_auth(client):
    resp = await client.get("/api/v1/arena/public/stats/global-index")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall" in data
    assert "archetypes" in data


async def test_global_index_empty_archetype_does_not_500_or_divide_by_zero(client):
    """No matches exist at all yet — must return a coherent zeroed shape,
    never a 500 or a NaN/inf from a 0/0 division."""
    resp = await client.get("/api/v1/arena/public/stats/global-index")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"]["total_matches"] == 0
    assert data["overall"]["decisive_matches"] == 0
    assert data["overall"]["containment_rate"] == 0.0
    assert data["overall"]["attacker_win_rate"] == 0.0
    assert data["overall"]["avg_resolution_minutes"] is None
    assert data["archetypes"] == []


async def test_global_index_exact_rate_math_against_known_fixture(client, db):
    """3 defender_won + 1 attacker_won decisive matches for archetype A =
    75% containment / 25% attacker-win; 2 abandoned matches must be
    reported separately and NEVER counted in either rate's denominator."""
    base = datetime(2026, 1, 1, 12, 0, 0)

    # 3 containments (defender_won), each resolved in exactly 10 minutes.
    for i in range(3):
        _make_match(
            db,
            archetype_key="archetype_a",
            status="defender_won",
            started_at=base,
            completed_at=base + timedelta(minutes=10),
            seed=100 + i,
        )
    # 1 attacker win, resolved in 30 minutes.
    _make_match(
        db,
        archetype_key="archetype_a",
        status="attacker_won",
        started_at=base,
        completed_at=base + timedelta(minutes=30),
        seed=200,
    )
    # 2 abandoned matches — must NOT count toward decisive_matches or either rate.
    _make_match(db, archetype_key="archetype_a", status="abandoned", started_at=base, completed_at=base + timedelta(minutes=5), seed=300)
    _make_match(db, archetype_key="archetype_a", status="abandoned", started_at=base, completed_at=base + timedelta(minutes=5), seed=301)

    # A non-terminal match must be excluded entirely (no completed_at).
    _make_match(db, archetype_key="archetype_a", status="active", started_at=base, completed_at=None, seed=400)

    await db.flush()
    await db.commit()

    resp = await client.get("/api/v1/arena/public/stats/global-index")
    assert resp.status_code == 200
    data = resp.json()

    bucket = next(a for a in data["archetypes"] if a["archetype_key"] == "archetype_a")
    assert bucket["total_matches"] == 6  # 3 + 1 + 2 abandoned (active excluded, no completed_at)
    assert bucket["decisive_matches"] == 4
    assert bucket["abandoned_count"] == 2
    assert bucket["containment_rate"] == 0.75
    assert bucket["attacker_win_rate"] == 0.25
    # (3*10 + 1*30) / 4 = 15.0 minutes
    assert bucket["avg_resolution_minutes"] == 15.0

    # overall must fold in the same rows (only this archetype exists here).
    assert data["overall"]["decisive_matches"] == 4
    assert data["overall"]["containment_rate"] == 0.75


async def test_global_index_skips_rows_missing_a_timestamp_for_resolution_avg(client, db):
    base = datetime(2026, 1, 1, 12, 0, 0)
    # Decisive but missing started_at — must count toward the rate but be
    # skipped from the avg_resolution_minutes computation.
    _make_match(db, archetype_key="archetype_b", status="defender_won", started_at=None, completed_at=base, seed=500)
    _make_match(db, archetype_key="archetype_b", status="defender_won", started_at=base, completed_at=base + timedelta(minutes=20), seed=501)
    await db.flush()
    await db.commit()

    resp = await client.get("/api/v1/arena/public/stats/global-index")
    data = resp.json()
    bucket = next(a for a in data["archetypes"] if a["archetype_key"] == "archetype_b")
    assert bucket["decisive_matches"] == 2
    assert bucket["containment_rate"] == 1.0
    assert bucket["avg_resolution_minutes"] == 20.0  # only the row with both timestamps


async def test_global_index_never_leaks_user_id(client, db, test_user, admin_user):
    base = datetime(2026, 1, 1, 12, 0, 0)
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=1,
        archetype_key="archetype_c",
        mode="pvp",
        attacker_user_id=test_user["user"].id,
        defender_user_id=admin_user["user"].id,
        status="defender_won",
        started_at=base,
        completed_at=base + timedelta(minutes=5),
    )
    db.add(match)
    await db.flush()
    await db.commit()

    resp = await client.get("/api/v1/arena/public/stats/global-index")
    assert resp.status_code == 200
    body_text = resp.text
    assert test_user["user"].id not in body_text
    assert admin_user["user"].id not in body_text
    assert "user_id" not in body_text
    assert "email" not in body_text
    assert "full_name" not in body_text


async def test_global_index_second_call_within_ttl_is_cached_and_idempotent(client, db):
    """Build fixture data, hit the endpoint once (populates the cache), add
    MORE matches, hit it again — the second response must be byte-identical
    to the first (served from cache, not recomputed), proving the TTL cache
    actually short-circuits the DB query rather than merely happening to
    return consistent numbers."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    _make_match(db, archetype_key="archetype_d", status="defender_won", started_at=base, completed_at=base + timedelta(minutes=10), seed=1)
    await db.flush()
    await db.commit()

    first = await client.get("/api/v1/arena/public/stats/global-index")
    assert first.status_code == 200
    first_data = first.json()

    # Add more matches AFTER the first call populated the cache.
    _make_match(db, archetype_key="archetype_d", status="attacker_won", started_at=base, completed_at=base + timedelta(minutes=99), seed=2)
    await db.flush()
    await db.commit()

    second = await client.get("/api/v1/arena/public/stats/global-index")
    assert second.status_code == 200
    second_data = second.json()

    assert second_data == first_data  # cache hit — new match not reflected yet

    # After clearing the cache (simulating TTL expiry), the new match IS reflected.
    _GLOBAL_INDEX_CACHE.clear()
    third = await client.get("/api/v1/arena/public/stats/global-index")
    third_data = third.json()
    bucket = next(a for a in third_data["archetypes"] if a["archetype_key"] == "archetype_d")
    assert bucket["total_matches"] == 2


# ── GET /scenarios/public/stats/{scenario_id} ───────────────────────────────

async def test_scenario_stats_reachable_without_auth(client, approved_scenario):
    resp = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert resp.status_code == 200


async def test_scenario_stats_404_for_unknown_scenario(client):
    resp = await client.get(f"/api/v1/scenarios/public/stats/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_scenario_stats_404_for_private_scenario(client, db, test_org):
    scenario = Scenario(
        title="Private Incident",
        source_type="manual",
        source_reference="PRIV-1",
        status="approved",
        is_private=True,
        owner_org_id=test_org.id,
    )
    db.add(scenario)
    await db.flush()
    await db.commit()

    resp = await client.get(f"/api/v1/scenarios/public/stats/{scenario.id}")
    assert resp.status_code == 404


async def test_scenario_stats_404_for_unapproved_scenario(client, db):
    scenario = Scenario(
        title="Still In Review",
        source_type="manual",
        source_reference="DRAFT-1",
        status="draft",
    )
    db.add(scenario)
    await db.flush()
    await db.commit()

    resp = await client.get(f"/api/v1/scenarios/public/stats/{scenario.id}")
    assert resp.status_code == 404


async def test_scenario_stats_no_sessions_does_not_500_or_divide_by_zero(client, approved_scenario):
    resp = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sessions"] == 0
    assert data["rated_sessions"] == 0
    assert data["success_rate"] == 0.0
    assert data["avg_decision_accuracy"] is None
    assert data["avg_team_score"] is None


async def test_scenario_stats_exact_rate_math_against_known_fixture(client, db, approved_scenario, test_user):
    """4 completed sessions: 3 at >=70% accuracy (success threshold), 1
    below — success_rate must be exactly 75%."""
    host_id = test_user["user"].id
    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=10, team_score=100.0)  # 100% -> success
    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=7, team_score=70.0)   # 70% -> success (>= threshold)
    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=8, team_score=80.0)   # 80% -> success
    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=2, team_score=20.0)   # 20% -> failure
    # Completed but never made a graded decision — must be excluded from rated_sessions entirely.
    _make_session(db, approved_scenario.id, host_id, decisions_made=0, decisions_correct=0, team_score=None)
    # Not completed — must be excluded from total_sessions entirely.
    _make_session(db, approved_scenario.id, host_id, decisions_made=5, decisions_correct=5, status="active")
    await db.flush()
    await db.commit()

    resp = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_sessions"] == 5  # 4 rated + 1 zero-decisions completed session
    assert data["rated_sessions"] == 4
    assert data["success_rate"] == 0.75
    # avg accuracy = (1.0 + 0.7 + 0.8 + 0.2) / 4 = 0.675
    assert data["avg_decision_accuracy"] == 0.675
    # avg team_score across the 4 scored sessions (the zero-decisions session had score=None, excluded)
    assert data["avg_team_score"] == 67.5


async def test_scenario_stats_never_leaks_user_id_or_session_id(client, db, approved_scenario, test_user):
    sess = _make_session(db, approved_scenario.id, test_user["user"].id, decisions_made=10, decisions_correct=9, team_score=90.0)
    await db.flush()
    await db.commit()
    session_id = sess.id

    resp = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert resp.status_code == 200
    body_text = resp.text
    assert test_user["user"].id not in body_text
    assert session_id not in body_text
    assert "user_id" not in body_text
    assert "host_user_id" not in body_text


async def test_scenario_stats_second_call_within_ttl_is_cached(client, db, approved_scenario, test_user):
    host_id = test_user["user"].id
    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=10, team_score=100.0)
    await db.flush()
    await db.commit()

    first = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert first.json()["total_sessions"] == 1

    _make_session(db, approved_scenario.id, host_id, decisions_made=10, decisions_correct=1, team_score=10.0)
    await db.flush()
    await db.commit()

    second = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert second.json() == first.json()  # still cached, new session not reflected

    from app.api.routes.scenarios import _SCENARIO_STATS_CACHE
    _SCENARIO_STATS_CACHE.clear()
    third = await client.get(f"/api/v1/scenarios/public/stats/{approved_scenario.id}")
    assert third.json()["total_sessions"] == 2
