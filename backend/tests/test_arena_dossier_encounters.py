"""Arena → Technique Dossier persistence (terminal match completion).

Covers role-asymmetric credit, dossier-eligible technique filtering, and the
shared `dossier_service.record_technique_encounters` upsert path.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.arena import ArenaAction, ArenaMatch
from app.models.technique_encounter import TechniqueEncounter
from app.services.dossier_service import (
    ARENA_DOSSIER_TECHNIQUE_IDS,
    collect_valid_arena_dossier_techniques,
    record_arena_match_encounters,
)
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    _replace_host,
    generate_org_state,
)
from app.websocket.handlers import _mark_match_completed_if_needed

pytestmark = pytest.mark.asyncio

FILTERED_ARENA_TECHNIQUE_IDS = frozenset({"T1046", "T1003.001", "T1550.002"})


async def _make_match(
    db,
    *,
    attacker_id=None,
    defender_id=None,
    mode="human_attacks_vs_ai",
    status="active",
    seed=13,
    archetype_key="small_healthcare",
):
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=archetype_key,
        mode=mode,
        attacker_user_id=attacker_id,
        defender_user_id=defender_id,
        status=status,
    )
    db.add(match)
    await db.flush()
    return match


async def _add_action(db, match_id: str, sequence_number: int, actor: str, action_type: str, payload: dict):
    db.add(ArenaAction(
        id=str(uuid.uuid4()),
        match_id=match_id,
        sequence_number=sequence_number,
        actor=actor,
        action_type=action_type,
        payload=payload,
    ))
    await db.flush()


def _base_state(seed=13, archetype_key="small_healthcare"):
    return generate_org_state(seed, ORG_ARCHETYPES[archetype_key])


async def test_arena_dossier_technique_ids_are_the_direct_three_sixths():
    assert ARENA_DOSSIER_TECHNIQUE_IDS == frozenset({"T1078", "T1068", "T1486"})
    assert FILTERED_ARENA_TECHNIQUE_IDS.isdisjoint(ARENA_DOSSIER_TECHNIQUE_IDS)


async def test_attacker_gets_credit_for_own_valid_actions_only(db, test_user):
    """Human attacker: valid gain_foothold credits T1078; a repeat on the same
    host is engine-rejected; recon/dump map to filtered IDs and must not write."""
    state = _base_state()
    target_host = state.hosts[0]
    segment = state.segments[0]

    match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=None)
    await _add_action(db, match.id, 0, "attacker", "gain_foothold", {"host_id": target_host.id})
    await _add_action(db, match.id, 1, "attacker", "gain_foothold", {"host_id": target_host.id})
    await _add_action(db, match.id, 2, "attacker", "discover_host", {"host_id": target_host.id})
    compromised = _replace_host(state, target_host.id, compromise_level="foothold")
    await _add_action(
        db, match.id, 3, "attacker", "dump_credentials", {"host_id": compromised.hosts[0].id},
    )
    await db.commit()

    await record_arena_match_encounters(db, match)
    await db.commit()

    result = await db.execute(
        select(TechniqueEncounter).where(TechniqueEncounter.user_id == test_user["user"].id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].technique_id == "T1078"
    assert rows[0].encounter_count == 1


async def test_defender_gets_credit_for_all_valid_attacker_actions_including_ai(db, test_user):
    """human_defends_vs_ai: defender earns attacker-side techniques the AI bot
    executed, without the attacker seat having a real user_id."""
    state = _base_state()
    host = next(h for h in state.hosts if h.unpatched_cves and not h.isolated)

    match = await _make_match(
        db,
        attacker_id=None,
        defender_id=test_user["user"].id,
        mode="human_defends_vs_ai",
    )
    await _add_action(db, match.id, 0, "attacker", "gain_foothold", {"host_id": host.id})
    await _add_action(
        db, match.id, 1, "attacker", "escalate_privilege", {"host_id": host.id},
    )
    await db.commit()

    await record_arena_match_encounters(db, match)
    await db.commit()

    result = await db.execute(
        select(TechniqueEncounter).where(TechniqueEncounter.user_id == test_user["user"].id)
    )
    technique_ids = {row.technique_id for row in result.scalars().all()}
    assert technique_ids == frozenset({"T1078", "T1068"})


async def test_ai_vs_ai_match_writes_no_encounters(db):
    state = _base_state()
    host = state.hosts[0]

    before = await db.scalar(select(func.count()).select_from(TechniqueEncounter))

    match = await _make_match(db, attacker_id=None, defender_id=None, mode="pvp")
    await _add_action(db, match.id, 0, "attacker", "gain_foothold", {"host_id": host.id})
    await db.commit()

    await record_arena_match_encounters(db, match)
    await db.commit()

    after = await db.scalar(select(func.count()).select_from(TechniqueEncounter))
    assert after == before


async def test_filtered_arena_technique_ids_never_create_orphan_rows(db, test_user):
    """Recon and credential-dump tag filtered IDs — only dossier-covered tags persist."""
    state = _base_state()
    host = state.hosts[0]
    segment = state.segments[0]

    match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=None)
    await _add_action(db, match.id, 0, "attacker", "gain_foothold", {"host_id": host.id})
    await _add_action(db, match.id, 1, "attacker", "discover_segment", {"segment_id": segment.id})
    await _add_action(db, match.id, 2, "attacker", "dump_credentials", {"host_id": host.id})
    await db.commit()

    collected = collect_valid_arena_dossier_techniques(match.seed, match.archetype_key, [
        {"sequence_number": 0, "actor": "attacker", "action_type": "gain_foothold", "payload": {"host_id": host.id}},
        {"sequence_number": 1, "actor": "attacker", "action_type": "discover_segment", "payload": {"segment_id": segment.id}},
        {"sequence_number": 2, "actor": "attacker", "action_type": "dump_credentials", "payload": {"host_id": host.id}},
    ])
    assert collected == frozenset({"T1078"})
    assert collected.isdisjoint(FILTERED_ARENA_TECHNIQUE_IDS)

    await record_arena_match_encounters(db, match)
    await db.commit()

    result = await db.execute(
        select(TechniqueEncounter).where(TechniqueEncounter.user_id == test_user["user"].id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].technique_id == "T1078"
    assert rows[0].technique_id not in FILTERED_ARENA_TECHNIQUE_IDS


async def test_mark_match_completed_if_needed_records_encounters_on_terminal_transition(db, test_user):
    """Integration: dossier write happens in the same completion transaction."""
    state = _base_state()
    host = state.hosts[0]

    match = await _make_match(db, attacker_id=test_user["user"].id, defender_id=None)
    await _add_action(db, match.id, 0, "attacker", "gain_foothold", {"host_id": host.id})
    await db.commit()

    terminal_state = _replace_host(state, host.id, compromise_level="admin")
    terminal_state = type(terminal_state)(
        hosts=terminal_state.hosts,
        segments=terminal_state.segments,
        credentials=terminal_state.credentials,
        detection_rules=terminal_state.detection_rules,
        global_flags={**terminal_state.global_flags, "impact_deployed": True},
    )

    result = await _mark_match_completed_if_needed(
        db, match.id, match.status, terminal_state, total_actions=1,
    )
    assert result["completed"] is True
    assert result["status"] == "attacker_won"

    rows = (await db.execute(
        select(TechniqueEncounter).where(TechniqueEncounter.user_id == test_user["user"].id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].technique_id == "T1078"
