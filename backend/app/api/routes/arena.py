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
from app.services import arena_matchmaking_service

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


# ── Phase G: branching debrief exploration ──────────────────────────────────

_COMPLETED_STATUSES = ("attacker_won", "defender_won", "abandoned")


class AlternateActionRequest(BaseModel):
    actor: str
    action_type: str
    payload: dict = {}

    @field_validator("actor")
    @classmethod
    def _validate_actor(cls, v: str) -> str:
        if v not in ("attacker", "defender"):
            raise ValueError("actor must be 'attacker' or 'defender'")
        return v


class ExploreMatchRequest(BaseModel):
    at_sequence_number: int
    alternate_action: AlternateActionRequest

    @field_validator("at_sequence_number")
    @classmethod
    def _validate_at_sequence_number(cls, v: int) -> int:
        if v < 0:
            raise ValueError("at_sequence_number must be >= 0")
        return v


@router.post("/matches/{match_id}/explore")
async def explore_match(
    match_id: str,
    payload: ExploreMatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase G — "what if I'd chosen differently at step N" branching debrief.

    100% READ-ONLY against arena_matches/arena_actions for the real match.
    This endpoint NEVER calls `_persist_arena_action` and NEVER writes to
    the `arena_actions` table — it loads the real, persisted action log,
    truncates it to `actions[:at_sequence_number]`, appends the caller's
    `alternate_action` in place of whatever really happened at that point
    (and everything after it, since actions after a divergence point no
    longer make sense against a state that never happened), and calls
    `org_simulation.replay()` — the exact same pure function
    `GET /arena/matches/{id}` uses to reconstruct real state — over that
    hypothetical log. The result is computed and returned; nothing is
    committed.

    Restricted to COMPLETED matches only (attacker_won | defender_won |
    abandoned): "explore alternate history" is a post-game debrief feature
    per the plan's framing (Phase G verification talks about "a completed
    match"), not a way to preview alternate futures against a still-live
    match's current state while it's in progress.
    """
    result = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if current_user.id not in (match.attacker_user_id, match.defender_user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this match")
    if match.status not in _COMPLETED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Exploration is only available for completed matches",
        )

    actions_result = await db.execute(
        select(ArenaAction)
        .where(ArenaAction.match_id == match_id)
        .order_by(ArenaAction.sequence_number)
    )
    action_rows = actions_result.scalars().all()
    real_action_dicts = [
        {
            "sequence_number": a.sequence_number,
            "actor": a.actor,
            "action_type": a.action_type,
            "payload": a.payload,
        }
        for a in action_rows
    ]

    if payload.at_sequence_number > len(real_action_dicts):
        raise HTTPException(
            status_code=400,
            detail=f"at_sequence_number out of range (match has {len(real_action_dicts)} actions)",
        )

    # Truncate to actions[:at_sequence_number] and append the alternate
    # action in place of the real one at that point — everything after the
    # divergence point is dropped, never read, never written anywhere.
    truncated = real_action_dicts[: payload.at_sequence_number]
    alternate_dict = {
        "sequence_number": payload.at_sequence_number,
        "actor": payload.alternate_action.actor,
        "action_type": payload.alternate_action.action_type,
        "payload": payload.alternate_action.payload,
    }
    hypothetical_actions = truncated + [alternate_dict]

    # Pure compute — no DB write of any kind below this line.
    alt_state, alt_events = replay(match.seed, match.archetype_key, hypothetical_actions)

    return {
        "match_id": match.id,
        "at_sequence_number": payload.at_sequence_number,
        "real_action_count": len(real_action_dicts),
        "alternate_action": alternate_dict,
        "state": alt_state.to_dict(),
        "events": alt_events,
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


# ── Phase I: matchmaking queue ──────────────────────────────────────────────
#
# Pairs two waiting humans into a fresh PvP match. Queue state lives
# in-process (app.websocket.manager.ConnectionManager.arena_queue) rather
# than a DB table — see arena_matchmaking_service.py's module docstring for
# why. Once paired, the resulting ArenaMatch is a completely normal match:
# the frontend navigates to it and plays it over the same
# /ws/arena/{match_id} WebSocket every other match uses.

@router.post("/queue/join")
async def join_matchmaking_queue(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Join the PvP matchmaking queue. Idempotent — calling this again while
    already queued (or already matched but not yet polled) just returns the
    current state instead of creating a duplicate entry."""
    return await arena_matchmaking_service.join_queue(db, current_user.id)


@router.get("/queue/status")
async def get_matchmaking_queue_status(
    current_user: User = Depends(get_current_user),
):
    """Poll queue state. Once `status == "matched"`, the entry is consumed
    server-side (won't be returned again) — the frontend should navigate to
    `match_id` immediately."""
    return await arena_matchmaking_service.queue_status(current_user.id)


@router.delete("/queue/leave")
async def leave_matchmaking_queue(
    current_user: User = Depends(get_current_user),
):
    """Leave the queue before being matched. No-op (returns left=False) if
    not currently queued, or if already matched (at that point the match
    itself exists — canceling it is the normal abandon-a-match path, not
    this endpoint)."""
    left = await arena_matchmaking_service.leave_queue(current_user.id)
    return {"left": left}


# ── Phase I: leaderboard ─────────────────────────────────────────────────────

@router.get("/leaderboard")
async def get_arena_leaderboard(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top arena players by ELO-style rating. Only players who have actually
    completed at least one rated match are listed — every user starts at
    the same default rating (1200), so including never-played accounts
    would just be noise, not a meaningful ranking."""
    limit = max(1, min(limit, 100))
    result = await db.execute(
        select(User)
        .where(User.arena_matches_played > 0)
        .order_by(desc(User.arena_rating))
        .limit(limit)
    )
    users = result.scalars().all()
    return [
        {
            "rank": i + 1,
            "user_id": u.id,
            "display_name": u.full_name or u.email,
            "arena_rating": u.arena_rating,
            "arena_wins": u.arena_wins,
            "arena_losses": u.arena_losses,
            "arena_matches_played": u.arena_matches_played,
            "is_current_user": u.id == current_user.id,
        }
        for i, u in enumerate(users)
    ]
