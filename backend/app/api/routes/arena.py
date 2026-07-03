"""
Live Arena Mode — REST endpoints for match lifecycle (Phase C).

Matches are created here (lobby state, initial seed) but played live over
the `/ws/arena/{match_id}` WebSocket (see app/websocket/handlers.py,
arena_ws_handler). The action log (`ArenaAction` rows) is the single
source of truth for match state — `GET /arena/matches/{id}` reconstructs
current state via `org_simulation.replay()`, never by trusting
`ArenaMatch.final_org_state_cache` (that field is only a cache, written
once a match actually completes).
"""
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.arena import ArenaMatch, ArenaAction
from app.models.user import User
from app.core.security import get_current_user
from app.services.org_simulation import ORG_ARCHETYPES, generate_org_state, replay

router = APIRouter(prefix="/arena", tags=["arena"])

_MODES = ("pvp", "human_defends_vs_ai", "human_attacks_vs_ai")
_DIFFICULTIES = ("easy", "medium", "hard")


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateMatchRequest(BaseModel):
    mode: str
    archetype_key: str
    attacker_user_id: Optional[str] = None
    defender_user_id: Optional[str] = None
    difficulty: str = "medium"

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        if v not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}")
        return v

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, v: str) -> str:
        if v not in _DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {_DIFFICULTIES}")
        return v


# ── Frontend-safe state summaries ───────────────────────────────────────────
#
# Neither side should receive the full raw OrgState at match creation: that
# would leak information a "Discovery"-equivalent attacker action or a
# defender's own tooling is supposed to reveal over the course of the match.
# Both summaries below expose only what's plausible to know before any
# actions have been taken.

def _attacker_initial_view(state) -> dict:
    """The attacker starts knowing nothing about the org beyond its coarse
    shape (segment count/names) — everything else (hosts, CVEs, credentials,
    detection coverage) must be earned via discover_segment/discover_host/
    dump_credentials actions."""
    return {
        "segment_count": len(state.segments),
        "segments": [{"id": s.id, "name": s.name} for s in state.segments],
        "host_count": len(state.hosts),
    }


def _defender_initial_view(state) -> dict:
    """The defender sees their own inventory (hosts, segments, credentials
    exist and their non-sensitive attributes) but NOT unpatched CVEs
    (patch status is a Discovery/vuln-scan-equivalent finding in this
    model) and not which specific detection rules exist under the hood —
    only that monitoring is or isn't on per segment, which is legitimately
    visible to a defender from day one."""
    return {
        "hosts": [
            {
                "id": h.id,
                "hostname": h.hostname,
                "role": h.role,
                "network_segment_id": h.network_segment_id,
                "edr_installed": h.edr_installed,
                "isolated": h.isolated,
            }
            for h in state.hosts
        ],
        "segments": [
            {"id": s.id, "name": s.name, "monitored": s.monitored}
            for s in state.segments
        ],
        "credential_count": len(state.credentials),
    }


def _match_summary(match: ArenaMatch) -> dict:
    return {
        "id": match.id,
        "mode": match.mode,
        "archetype_key": match.archetype_key,
        "difficulty": match.difficulty,
        "status": match.status,
        "attacker_user_id": match.attacker_user_id,
        "defender_user_id": match.defender_user_id,
        "started_at": match.started_at.isoformat() if match.started_at else None,
        "completed_at": match.completed_at.isoformat() if match.completed_at else None,
        "created_at": match.created_at.isoformat() if match.created_at else None,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/matches", status_code=status.HTTP_201_CREATED)
async def create_match(
    payload: CreateMatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new arena match in `lobby` status and generate its initial
    (seeded) OrgState. The seed itself is chosen with `secrets.SystemRandom`
    — non-deterministic randomness is fine here, since this is choosing the
    match's starting conditions, not anything inside the simulation
    engine's pure functions (those stay fully deterministic given the
    seed)."""
    if payload.archetype_key not in ORG_ARCHETYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown archetype_key. Valid keys: {sorted(ORG_ARCHETYPES.keys())}",
        )

    attacker_user_id = payload.attacker_user_id
    defender_user_id = payload.defender_user_id

    if payload.mode == "human_defends_vs_ai":
        defender_user_id = current_user.id
        attacker_user_id = None
    elif payload.mode == "human_attacks_vs_ai":
        attacker_user_id = current_user.id
        defender_user_id = None
    else:  # pvp
        if not attacker_user_id and not defender_user_id:
            # Default: current user is the attacker, opponent TBD (lobby fills defender later).
            attacker_user_id = current_user.id
        elif current_user.id not in (attacker_user_id, defender_user_id):
            raise HTTPException(
                status_code=400,
                detail="pvp mode requires the current user to be either the attacker_user_id or defender_user_id",
            )

    # random.SystemRandom / secrets.randbelow: non-deterministic seed choice
    # is intentional and safe HERE ONLY — never inside org_simulation.py's
    # pure functions, which must stay deterministic given a seed.
    seed = secrets.randbelow(2**31 - 1)

    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=payload.archetype_key,
        mode=payload.mode,
        attacker_user_id=attacker_user_id,
        defender_user_id=defender_user_id,
        difficulty=payload.difficulty,
        status="lobby",
        created_at=datetime.utcnow(),
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)

    initial_state = generate_org_state(match.seed, ORG_ARCHETYPES[match.archetype_key])

    return {
        **_match_summary(match),
        "attacker_view": _attacker_initial_view(initial_state),
        "defender_view": _defender_initial_view(initial_state),
    }


@router.get("/matches/{match_id}")
async def get_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return match status plus the CURRENT state, reconstructed via
    `org_simulation.replay()` over this match's persisted ArenaAction log —
    the one correct way to get current state. `final_org_state_cache` is
    never read here; it exists only to speed up debrief loading once a
    match has actually completed."""
    result = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if current_user.id not in (match.attacker_user_id, match.defender_user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this match")

    actions_result = await db.execute(
        select(ArenaAction)
        .where(ArenaAction.match_id == match_id)
        .order_by(ArenaAction.sequence_number)
    )
    action_rows = actions_result.scalars().all()
    action_dicts = [
        {
            "sequence_number": a.sequence_number,
            "actor": a.actor,
            "action_type": a.action_type,
            "payload": a.payload,
        }
        for a in action_rows
    ]

    final_state, events = replay(match.seed, match.archetype_key, action_dicts)

    return {
        **_match_summary(match),
        "action_count": len(action_dicts),
        "state": final_state.to_dict(),
        "events": events,
    }


@router.get("/matches")
async def list_my_matches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's arena matches (as attacker or defender)."""
    result = await db.execute(
        select(ArenaMatch)
        .where(
            or_(
                ArenaMatch.attacker_user_id == current_user.id,
                ArenaMatch.defender_user_id == current_user.id,
            )
        )
        .order_by(desc(ArenaMatch.created_at))
        .limit(50)
    )
    matches = result.scalars().all()
    return [_match_summary(m) for m in matches]
