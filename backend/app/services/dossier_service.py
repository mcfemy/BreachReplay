"""
Technique Dossier — per-user aggregation over `TechniqueEncounter` rollup
rows (backend/app/models/technique_encounter.py), joined against the static
`TECHNIQUE_DOSSIER` content (backend/app/services/technique_dossier.py) for
display. Shaped after `mastery_service.compute_user_mastery` — pure
query-time aggregation, no business logic beyond the join — but a distinct
source table: mastery aggregates `SessionDecision`/`RedTeamMove` attempts,
this aggregates Action Console technique *encounters*
(`verb_engine.RunState.encountered_technique_ids`, persisted only for
authenticated runs by `action_run_store.finalize`).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.technique_encounter import TechniqueEncounter
from app.services.technique_dossier import TECHNIQUE_DOSSIER


async def compute_user_dossier(db: AsyncSession, user_id: str) -> dict:
    """
    Every technique in TECHNIQUE_DOSSIER, joined against this user's
    TechniqueEncounter rows (if any). A technique with no row is still
    included — `encountered: False`, `encounter_count: 0` — so the caller
    can render the full 30-technique dossier with locked/unlocked state,
    not just the subset the user has hit so far.

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
            "incident_narrative": content["incident_narrative"],
            "source_reference": content["source_reference"],
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
