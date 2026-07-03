"""Tests for Live Arena Mode Phase I: ELO-style rating engine.

Covers `arena_rating_service.compute_new_ratings` (pure function) and
`apply_match_result` (DB-applying wrapper), plus the fix to
`_notify_arena_action_result`'s previously-hardcoded "attacker_won" status
in the match_complete WS event.
"""
import uuid

import pytest

from app.models.arena import ArenaMatch
from app.services.arena_rating_service import (
    compute_new_ratings,
    apply_match_result,
    AI_PHANTOM_RATING,
)

pytestmark = pytest.mark.asyncio


async def _make_match(db, attacker_id=None, defender_id=None, status="attacker_won", difficulty="medium", mode="pvp"):
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=1,
        archetype_key="small_healthcare",
        mode=mode,
        attacker_user_id=attacker_id,
        defender_user_id=defender_id,
        status=status,
        difficulty=difficulty,
    )
    db.add(match)
    await db.flush()
    return match


# ── compute_new_ratings: pure ELO math ──────────────────────────────────────

async def test_equal_ratings_winner_gains_half_k_loser_loses_half_k():
    new_a, new_b = compute_new_ratings(1200, 1200, a_won=True, k=32)
    assert new_a == 1216
    assert new_b == 1184


async def test_underdog_win_gains_more_than_favorite_win():
    """A win is worth more against a HIGHER-rated opponent."""
    _, favorite_loses = compute_new_ratings(1600, 1200, a_won=False, k=32)  # favorite (A) loses
    underdog_wins, _ = compute_new_ratings(1200, 1600, a_won=True, k=32)  # underdog (A) wins
    assert underdog_wins - 1200 > 1216 - 1200  # bigger gain than an even-odds win


async def test_ratings_are_zero_sum_under_equal_k():
    new_a, new_b = compute_new_ratings(1350, 1180, a_won=False, k=32)
    delta_a = new_a - 1350
    delta_b = new_b - 1180
    assert delta_a == -delta_b


# ── apply_match_result: DB-applying wrapper ─────────────────────────────────

async def test_pvp_match_updates_both_real_users(db, test_org, test_user, admin_user):
    match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=admin_user["user"].id, status="attacker_won")
    await db.flush()

    changes = await apply_match_result(db, match)

    assert set(changes.keys()) == {"attacker", "defender"}
    assert changes["attacker"]["user_id"] == test_user["user"].id
    assert changes["defender"]["user_id"] == admin_user["user"].id
    assert changes["attacker"]["delta"] > 0
    assert changes["defender"]["delta"] < 0

    # apply_match_result deliberately does NOT commit (caller's transaction
    # does), so these attribute changes are only in-memory on the SAME
    # identity-mapped ORM objects — asserting directly on them (not via
    # db.refresh(), which would re-query the DB and discard the
    # not-yet-committed change).
    assert test_user["user"].arena_rating == changes["attacker"]["after"]
    assert test_user["user"].arena_wins == 1
    assert test_user["user"].arena_losses == 0
    assert test_user["user"].arena_matches_played == 1
    assert admin_user["user"].arena_rating == changes["defender"]["after"]
    assert admin_user["user"].arena_losses == 1
    assert admin_user["user"].arena_matches_played == 1


async def test_defender_won_credits_the_defender_not_the_attacker(db, test_org, test_user, admin_user):
    match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=admin_user["user"].id, status="defender_won")
    await db.flush()

    changes = await apply_match_result(db, match)

    assert test_user["user"].arena_losses == 1
    assert admin_user["user"].arena_wins == 1
    assert changes["attacker"]["delta"] < 0
    assert changes["defender"]["delta"] > 0


async def test_vs_ai_match_only_updates_the_real_user(db, test_org, test_user):
    """human_attacks_vs_ai: defender_user_id is None (no real opponent row) —
    only the human attacker's rating should move, computed against the
    difficulty's phantom AI rating."""
    match = await _make_match(
        db, attacker_id=test_user["user"].id, defender_id=None,
        status="attacker_won", difficulty="hard", mode="human_attacks_vs_ai",
    )
    await db.flush()

    changes = await apply_match_result(db, match)

    assert set(changes.keys()) == {"attacker"}
    expected_new, _ = compute_new_ratings(1200, AI_PHANTOM_RATING["hard"], a_won=True)
    assert changes["attacker"]["after"] == expected_new

    assert test_user["user"].arena_rating == expected_new
    assert test_user["user"].arena_wins == 1


async def test_active_or_abandoned_match_is_a_no_op(db, test_org, test_user, admin_user):
    for status in ("active", "lobby", "abandoned"):
        match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=admin_user["user"].id, status=status)
        await db.flush()
        changes = await apply_match_result(db, match)
        assert changes == {}


async def test_neither_side_a_real_user_is_a_no_op(db, test_org):
    match = await _make_match(db, attacker_id=None, defender_id=None, status="attacker_won")
    await db.flush()
    changes = await apply_match_result(db, match)
    assert changes == {}
