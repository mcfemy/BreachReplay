"""
Technique Dossier — per-user aggregation over `TechniqueEncounter` rollup
rows (backend/app/models/technique_encounter.py), joined against the static
`TECHNIQUE_DOSSIER` content (backend/app/services/technique_dossier.py) for
display. Shaped after `mastery_service.compute_user_mastery` — pure
query-time aggregation, no business logic beyond the join — but a distinct
source table: mastery aggregates `SessionDecision`/`RedTeamMove` attempts,
this aggregates technique *encounters* from Action Console runs
(`verb_engine.RunState.encountered_technique_ids`, persisted by
`action_run_store.finalize`) and Live Arena matches
(`record_arena_match_encounters`, on terminal match completion).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.arena import ArenaAction
from app.models.technique_encounter import TechniqueEncounter
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    _ACTION_TECHNIQUE_IDS,
    _derive_rng,
    apply_attacker_action,
    apply_defender_action,
    attacker_action_was_accepted,
    generate_org_state,
)
from app.services.technique_dossier import TECHNIQUE_DOSSIER

# Arena attacker actions tag six MITRE IDs; only three have dossier entries
# today — ship credit for those only (no parent/sub-technique normalization).
ARENA_DOSSIER_TECHNIQUE_IDS = frozenset(
    technique_id
    for technique_id in set(_ACTION_TECHNIQUE_IDS.values())
    if technique_id in TECHNIQUE_DOSSIER
)


async def record_technique_encounters(
    db: AsyncSession, user_id: str, technique_ids: frozenset,
) -> None:
    """Technique Dossier rollup — one `TechniqueEncounter` row per
    (user_id, technique_id), incrementing `encounter_count` on repeat
    exposure. Shared by Action Console finalize and Arena match completion.
    Get-or-create via a plain select, matching this codebase's existing
    convention for per-user rollup rows (e.g. `daily._get_or_create_streak`)
    rather than a DB-specific upsert."""
    if not technique_ids:
        return
    now = datetime.utcnow()
    for technique_id in technique_ids:
        result = await db.execute(
            select(TechniqueEncounter).where(
                TechniqueEncounter.user_id == user_id,
                TechniqueEncounter.technique_id == technique_id,
            )
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            db.add(TechniqueEncounter(
                user_id=user_id, technique_id=technique_id,
                encounter_count=1, first_encountered_at=now, last_encountered_at=now,
            ))
        else:
            encounter.encounter_count += 1
            encounter.last_encountered_at = now


def collect_valid_arena_dossier_techniques(
    seed: int, archetype_key: str, actions: list[dict],
) -> frozenset[str]:
    """Walk an ordered Arena action log and return dossier-eligible MITRE IDs
    from engine-accepted attacker actions. Defender-role credit uses the
    full attacker-side set; attacker-role credit uses the same set because
    every `actor=="attacker"` row belongs to the match's attacker seat."""
    archetype = ORG_ARCHETYPES.get(archetype_key, {})
    state = generate_org_state(seed, archetype)
    techniques: set[str] = set()

    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        actor = action.get("actor")
        sequence_number = action.get("sequence_number", i)

        if actor == "attacker":
            action_for_engine = {
                "action_type": action.get("action_type"),
                "payload": action.get("payload") or {},
                "sequence_number": sequence_number,
            }
            rng = _derive_rng(seed, sequence_number)
            prev_state = state
            state, _detected, _alert = apply_attacker_action(state, action_for_engine, rng)
            if attacker_action_was_accepted(prev_state, action_for_engine, state):
                technique_id = _ACTION_TECHNIQUE_IDS.get(action.get("action_type"))
                if technique_id in ARENA_DOSSIER_TECHNIQUE_IDS:
                    techniques.add(technique_id)
        elif actor == "defender":
            state = apply_defender_action(state, action)

    return frozenset(techniques)


async def record_arena_match_encounters(db: AsyncSession, match) -> None:
    """Persist Technique Dossier progress for human Arena participants when
    a match reaches a decisive terminal status. No-op when neither seat has a
    real user (same gate as `arena_rating_service.apply_match_result`)."""
    if match.attacker_user_id is None and match.defender_user_id is None:
        return

    a_res = await db.execute(
        select(ArenaAction)
        .where(ArenaAction.match_id == match.id)
        .order_by(ArenaAction.sequence_number)
    )
    action_dicts = [
        {
            "sequence_number": a.sequence_number,
            "actor": a.actor,
            "action_type": a.action_type,
            "payload": a.payload,
        }
        for a in a_res.scalars().all()
    ]

    techniques = collect_valid_arena_dossier_techniques(
        match.seed, match.archetype_key, action_dicts,
    )
    if not techniques:
        return

    if match.attacker_user_id:
        await record_technique_encounters(db, match.attacker_user_id, techniques)
    if match.defender_user_id:
        await record_technique_encounters(db, match.defender_user_id, techniques)


async def compute_user_dossier(db: AsyncSession, user_id: str) -> dict:
    """
    Every technique in TECHNIQUE_DOSSIER, joined against this user's
    TechniqueEncounter rows (if any). A technique with no row is still
    included — `encountered: False`, `encounter_count: 0` — so the caller
    can render the full 30-technique dossier with locked/unlocked state,
    not just the subset the user has hit so far. `incident_narrative` and
    `source_reference` are only populated for encountered techniques —
    the frontend's lock is cosmetic (name blurred client-side), so those
    fields must be withheld server-side or the lock isn't a real data
    boundary. `name`/`description` stay visible for browsing.

    Returns:
        {
            "techniques": {technique_id: {..dossier content.., "encountered": bool,
                            "encounter_count": int, "first_encountered_at": iso|None,
                            "last_encountered_at": iso|None}},
            "total_techniques": int,
            "encountered_count": int,
        }
    """
    result = await db.execute(
        select(TechniqueEncounter).where(TechniqueEncounter.user_id == user_id)
    )
    encounters_by_technique = {row.technique_id: row for row in result.scalars().all()}

    techniques: dict[str, dict] = {}
    encountered_count = 0
    for technique_id, content in TECHNIQUE_DOSSIER.items():
        encounter = encounters_by_technique.get(technique_id)
        encountered = encounter is not None
        if encountered:
            encountered_count += 1
        techniques[technique_id] = {
            "technique_id": technique_id,
            "name": content["name"],
            "tactic": content["tactic"],
            "description": content["description"],
            "incident_narrative": content["incident_narrative"] if encountered else None,
            "source_reference": content["source_reference"] if encountered else None,
            "scenarios": content["scenarios"],
            "encountered": encountered,
            "encounter_count": encounter.encounter_count if encounter else 0,
            "first_encountered_at": encounter.first_encountered_at.isoformat() if encounter else None,
            "last_encountered_at": encounter.last_encountered_at.isoformat() if encounter else None,
        }

    return {
        "techniques": techniques,
        "total_techniques": len(TECHNIQUE_DOSSIER),
        "encountered_count": encountered_count,
    }
