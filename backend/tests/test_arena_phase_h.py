"""Tests for Live Arena Mode Phase H: symmetric win conditions.

Covers the two new things Phase H adds on top of Phase C's
attacker-only-win-condition:
  1. `check_defender_containment` (app/services/org_simulation.py) — a pure
     function computed from OrgState.
  2. `_mark_match_completed_if_needed`'s new `total_actions` parameter and
     defender-win / turn-budget-fallback branches
     (app/websocket/handlers.py).

Regression coverage for the pre-existing attacker-win path is included so
Phase H's changes are proven not to have altered it.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.arena import ArenaMatch
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    generate_org_state,
    check_defender_containment,
)
from app.websocket.handlers import _mark_match_completed_if_needed, _MAX_MATCH_ACTIONS

pytestmark = pytest.mark.asyncio


async def _make_match(db, status="active", seed=13, archetype_key="small_healthcare"):
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=archetype_key,
        mode="pvp",
        attacker_user_id="attacker-1",
        defender_user_id="defender-1",
        status=status,
    )
    db.add(match)
    await db.flush()
    return match


# ── check_defender_containment: pure-function unit tests ────────────────────

def _base_state():
    return generate_org_state(13, ORG_ARCHETYPES["small_healthcare"])


async def test_containment_false_on_fresh_untouched_state():
    """A freshly generated OrgState must NOT count as containment: nothing
    was ever compromised, so there is nothing for the defender to have
    contained. This is the exact false-positive an earlier version of
    check_defender_containment got wrong (it only checked for the ABSENCE
    of uncontained compromise, which a pristine state trivially satisfies)."""
    assert check_defender_containment(_base_state()) is False


async def test_containment_false_while_a_compromised_host_is_not_isolated():
    state = _base_state()
    host = state.hosts[0]
    from app.services.org_simulation import _replace_host
    compromised = _replace_host(state, host.id, compromise_level="foothold")
    assert check_defender_containment(compromised) is False


async def test_containment_true_once_the_only_compromised_host_is_isolated():
    state = _base_state()
    host = state.hosts[0]
    from app.services.org_simulation import _replace_host
    compromised = _replace_host(state, host.id, compromise_level="admin")
    contained = _replace_host(compromised, host.id, isolated=True)
    assert check_defender_containment(contained) is True


async def test_containment_false_while_a_harvested_credential_remains_enabled():
    """Isolated on its own is not enough — a still-usable harvested
    credential means the attacker can still pivot elsewhere."""
    state = _base_state()
    host = state.hosts[0]
    cred = state.credentials[0]
    from app.services.org_simulation import _replace_host, _replace_credential
    state = _replace_host(state, host.id, compromise_level="admin", isolated=True)
    harvested = _replace_credential(state, cred.id, harvested=True)
    assert check_defender_containment(harvested) is False


async def test_containment_true_once_harvested_credential_is_disabled():
    state = _base_state()
    host = state.hosts[0]
    cred = state.credentials[0]
    from app.services.org_simulation import _replace_host, _replace_credential
    # Need an actual (contained) compromise present too, or "nothing was
    # ever compromised" short-circuits this to False regardless of the
    # credential's disabled flag.
    state = _replace_host(state, host.id, compromise_level="admin", isolated=True)
    harvested = _replace_credential(state, cred.id, harvested=True)
    assert check_defender_containment(harvested) is False
    disabled = _replace_credential(harvested, cred.id, disabled=True)
    assert check_defender_containment(disabled) is True


# ── _mark_match_completed_if_needed: integration tests against a real DB row ──

async def test_attacker_wins_on_impact_deployed_regression(db, test_org):
    """Phase C's original behavior must be unchanged by Phase H."""
    match = await _make_match(db)
    await db.commit()

    state = _base_state()
    state = type(state)(
        hosts=state.hosts, segments=state.segments, credentials=state.credentials,
        detection_rules=state.detection_rules,
        global_flags={**state.global_flags, "impact_deployed": True},
    )

    result = await _mark_match_completed_if_needed(db, match.id, match.status, state, total_actions=5)
    assert result["completed"] is True
    assert result["status"] == "attacker_won"

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.status == "attacker_won"
    assert m.completed_at is not None


async def test_active_match_does_not_false_positive_on_fresh_state(db, test_org):
    """A fresh, untouched OrgState trivially satisfies containment, but with
    total_actions below the minimum threshold this must NOT be treated as a
    defender win — otherwise every match would instantly end at creation."""
    match = await _make_match(db)
    await db.commit()

    state = _base_state()
    result = await _mark_match_completed_if_needed(db, match.id, match.status, state, total_actions=0)
    assert result["completed"] is False
    assert result["status"] is None
    assert result["rating_changes"] == {}

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.status == "active"
    assert m.completed_at is None


async def test_defender_wins_on_real_containment_once_min_actions_met(db, test_org):
    """The actually-reachable defender-win path: attacker compromises a host,
    defender isolates it and disables any harvested credential — a REAL,
    checkable OrgState condition, not a guessed one."""
    match = await _make_match(db)
    await db.commit()

    state = _base_state()
    host = state.hosts[0]
    cred = state.credentials[0]
    from app.services.org_simulation import _replace_host, _replace_credential
    state = _replace_host(state, host.id, compromise_level="admin", isolated=True)
    state = _replace_credential(state, cred.id, harvested=True, disabled=True)

    result = await _mark_match_completed_if_needed(db, match.id, match.status, state, total_actions=3)
    assert result["completed"] is True
    assert result["status"] == "defender_won"

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.status == "defender_won"
    assert m.completed_at is not None


async def test_turn_budget_cap_terminates_a_gridlocked_match(db, test_org):
    """Even if containment is never technically achieved and impact never
    deployed, a match must still terminate decisively once total_actions
    hits the turn-budget ceiling — the defender wins by survival."""
    match = await _make_match(db)
    await db.commit()

    state = _base_state()
    host = state.hosts[0]
    from app.services.org_simulation import _replace_host
    # Compromised but NOT isolated: containment is false, impact not deployed.
    gridlocked = _replace_host(state, host.id, compromise_level="foothold")

    not_yet = await _mark_match_completed_if_needed(
        db, match.id, match.status, gridlocked, total_actions=_MAX_MATCH_ACTIONS - 1,
    )
    assert not_yet["completed"] is False

    result = await _mark_match_completed_if_needed(
        db, match.id, match.status, gridlocked, total_actions=_MAX_MATCH_ACTIONS,
    )
    assert result["completed"] is True
    assert result["status"] == "defender_won"

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.status == "defender_won"


async def test_already_terminal_match_status_is_a_no_op(db, test_org):
    """Once a match has already resolved, re-evaluating must not flip it or
    re-write completed_at (idempotency across the two call sites in
    _execute_arena_action, and against any late-arriving stale action)."""
    match = await _make_match(db, status="attacker_won")
    await db.commit()

    state = _base_state()
    result = await _mark_match_completed_if_needed(db, match.id, "attacker_won", state, total_actions=99)
    assert result["completed"] is False

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.status == "attacker_won"
    assert m.completed_at is None
