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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.arena import ArenaMatch, ArenaAction
from app.models.arena_event import ArenaEvent
from app.models.user import User
from app.core.security import get_current_user
from app.core.stats_cache import TTLCache
from app.services.org_simulation import ORG_ARCHETYPES, generate_org_state, replay
from app.services import arena_matchmaking_service
from app.services.arena_event_service import arena_event_summary
from app.websocket.manager import manager

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
        # Live Breach Events Phase 4 — None for matches not paired under an event.
        "event_id": match.event_id,
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


# ── Live Breach Events Phase 1: public share links ──────────────────────────
#
# Any completed match can get a public, no-login-required URL — the primary
# organic-growth loop (posted to Discord/Twitter/LinkedIn). Two routes:
#   POST /arena/matches/{id}/share            — auth, participant-only, mints/returns the token
#   GET  /arena/public/replay/{share_token}    — no auth at all, redacted summary only
#
# Deliberately does NOT proxy to explore_match's branching-replay logic —
# that endpoint accepts arbitrary caller-supplied hypothetical actions with
# no rate limiting, and opening it publicly would multiply abuse surface for
# a "nice to have." Out of scope for this phase.

@router.post("/matches/{match_id}/share")
async def share_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or idempotently return) a public share token for a completed
    match. Same 403 "participant only" guard as `get_match`."""
    result = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if current_user.id not in (match.attacker_user_id, match.defender_user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this match")
    if match.status not in _COMPLETED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Sharing is only available once a match has completed",
        )

    if match.share_token:
        return {"share_token": match.share_token, "share_url_path": f"/replay/{match.share_token}"}

    # Re-fetch with a row-level lock right before the mint-and-commit
    # section: two participants (e.g. attacker + defender) hitting this
    # endpoint at the same moment would otherwise each generate a
    # *different* random token for the same match, and since the tokens
    # differ the unique constraint never fires — the second COMMIT would
    # silently overwrite the first writer's token. Locking the row makes
    # the second request block until the first transaction commits, then
    # see the now-set share_token below and return it idempotently instead
    # of overwriting it.
    locked_result = await db.execute(
        select(ArenaMatch).where(ArenaMatch.id == match_id).with_for_update()
    )
    match = locked_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.share_token:
        return {"share_token": match.share_token, "share_url_path": f"/replay/{match.share_token}"}

    # secrets.token_urlsafe(16) has enough entropy that a collision is
    # vanishingly unlikely, but the column is unique — retry a handful of
    # times on IntegrityError as defense-in-depth (the row lock above is
    # the primary fix for the concurrent-mint race above; this loop now
    # mainly guards against a true random-token collision).
    for _ in range(5):
        candidate = secrets.token_urlsafe(16)
        match.share_token = candidate
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            # Re-attach match to the session after rollback before retrying.
            result = await db.execute(
                select(ArenaMatch).where(ArenaMatch.id == match_id).with_for_update()
            )
            match = result.scalar_one_or_none()
            if match is None:
                raise HTTPException(status_code=404, detail="Match not found")
            if match.share_token:
                return {"share_token": match.share_token, "share_url_path": f"/replay/{match.share_token}"}
    else:
        raise HTTPException(status_code=500, detail="Could not generate a unique share token")

    return {"share_token": match.share_token, "share_url_path": f"/replay/{match.share_token}"}


def _public_participant_label(user: Optional[User], role_placeholder: str) -> str:
    """Resolve a participant's public-facing label: their opted-in display
    handle if they've explicitly enabled arena_profile_public, otherwise a
    stable per-role placeholder ("Player A"/"Player B") — never randomized,
    so repeat views of the same link are consistent, and never the raw
    user_id or full_name (full_name may be a real OAuth name)."""
    if user and user.arena_profile_public and user.public_display_handle:
        return user.public_display_handle
    return role_placeholder


@router.get("/public/replay/{share_token}")
async def get_public_replay(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public, no-auth match replay summary — the link posted to Discord/
    Twitter/LinkedIn. Hard-gated to terminal statuses only as defense-in-
    depth (a token is only ever minted for a completed match in the first
    place, but this route never trusts that alone). Reads state from
    `final_org_state_cache` rather than calling `replay()` — avoiding that
    recomputation on a public, potentially crawled endpoint is the whole
    point of the cache.

    NOTE: this route is intentionally unauthenticated and has no rate
    limiting applied. slowapi (see app.core.security.limiter) is already
    used elsewhere in this codebase (auth.py, ingestion.py) — if this route
    sees real abuse/crawling volume, apply the same `@limiter.limit(...)`
    decorator convention used there. Left as a follow-up per the phase 1 plan
    rather than adding it speculatively now.
    """
    result = await db.execute(select(ArenaMatch).where(ArenaMatch.share_token == share_token))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Replay not found")
    if match.status not in _COMPLETED_STATUSES:
        # Never expose in-progress match state on a public route — treat a
        # non-terminal match exactly like an unknown token (404, not 400),
        # since a token is only ever minted for an already-terminal match.
        raise HTTPException(status_code=404, detail="Replay not found")

    attacker_user, defender_user = None, None
    if match.attacker_user_id:
        attacker_result = await db.execute(select(User).where(User.id == match.attacker_user_id))
        attacker_user = attacker_result.scalar_one_or_none()
    if match.defender_user_id:
        defender_result = await db.execute(select(User).where(User.id == match.defender_user_id))
        defender_user = defender_result.scalar_one_or_none()

    actions_result = await db.execute(
        select(ArenaAction)
        .where(ArenaAction.match_id == match.id)
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

    # final_org_state_cache is populated by _mark_match_completed_if_needed
    # (app/websocket/handlers.py) at the moment a match reaches a terminal
    # status — never None for a match that passed the status check above,
    # but guard defensively anyway rather than assuming.
    state = match.final_org_state_cache or {}

    # events (detected/alert) shape mirrors what get_match returns today, but
    # replay() isn't called here — the alert/detected metadata already lives
    # on the persisted ArenaAction payload is NOT captured that way (get_match
    # derives it from replay()'s event stream). Since the whole point of this
    # route is avoiding replay() recomputation, the public timeline exposes
    # the actor/action_type/sequence_number from the real action log directly
    # (no detected/alert annotations) rather than recomputing them.
    events = [
        {
            "sequence_number": a["sequence_number"],
            "actor": a["actor"],
            "action_type": a["action_type"],
        }
        for a in action_dicts
    ]

    return {
        "archetype_key": match.archetype_key,
        "difficulty": match.difficulty,
        "mode": match.mode,
        "status": match.status,
        "started_at": match.started_at.isoformat() if match.started_at else None,
        "completed_at": match.completed_at.isoformat() if match.completed_at else None,
        "action_count": len(action_dicts),
        "attacker_label": _public_participant_label(attacker_user, "Player A"),
        "defender_label": _public_participant_label(defender_user, "Player B"),
        "state": state,
        "events": events,
    }


# ── Live Breach Events Phase 3: public aggregate stats ──────────────────────
#
# GET /arena/public/stats/global-index — no auth, cohort-only aggregate rates
# per archetype_key (never a per-user or per-match breakdown — see
# _compute_archetype_bucket below, which only ever reads/returns counts and
# derived rates). Cached in-process via app.core.stats_cache.TTLCache (see
# that module's docstring for the Redis-vs-in-process reasoning) with a 5
# minute TTL — comfortably inside the plan's stated 5-10 min window: short
# enough that a burst of newly-completed matches shows up quickly, long
# enough that a public, potentially crawled endpoint isn't re-aggregating
# the whole arena_matches table on every hit. Migration 0026 adds the
# compound (archetype_key, status, completed_at) index this query's WHERE
# clause and grouping rely on.
#
# Containment/attacker-win rate definitions (documented here since this
# feeds a public marketing page — a coherent story matters more than
# capturing every edge case):
#   - "terminal" match = completed_at IS NOT NULL AND status in
#     (attacker_won, defender_won, abandoned).
#   - "decisive" match = terminal AND status in (attacker_won, defender_won).
#     Abandoned matches are EXCLUDED from the rate denominator entirely —
#     an abandoned match (someone quit/disconnected) has no real winner, so
#     folding it into either rate as an implicit loss for one side would
#     misrepresent both sides' actual performance. abandoned_count is still
#     reported per-bucket for transparency; it's just never a denominator.
#   - containment_rate = defender_won / decisive_matches
#   - attacker_win_rate = attacker_won / decisive_matches
#   - avg_resolution_minutes = mean (completed_at - started_at) in minutes
#     over decisive matches where BOTH timestamps are present (a row
#     missing either is skipped, never treated as a 0-minute resolution).
#   - Any bucket with zero decisive matches reports both rates as 0.0 and
#     avg_resolution_minutes as None, rather than dividing by zero.

_GLOBAL_INDEX_CACHE = TTLCache(ttl_seconds=300)
_STATS_DECISIVE_STATUSES = ("attacker_won", "defender_won")


def _compute_archetype_bucket(archetype_key: Optional[str], rows: list) -> dict:
    """rows: iterable of objects with .status / .started_at / .completed_at
    (either ArenaMatch instances or SQLAlchemy Row tuples from a column-only
    select — both expose these as attributes)."""
    total_matches = len(rows)
    abandoned_count = sum(1 for r in rows if r.status == "abandoned")
    decisive_rows = [r for r in rows if r.status in _STATS_DECISIVE_STATUSES]
    decisive_matches = len(decisive_rows)
    defender_wins = sum(1 for r in decisive_rows if r.status == "defender_won")
    attacker_wins = sum(1 for r in decisive_rows if r.status == "attacker_won")

    resolution_minutes = [
        (r.completed_at - r.started_at).total_seconds() / 60.0
        for r in decisive_rows
        if r.started_at is not None and r.completed_at is not None
    ]

    bucket = {
        "total_matches": total_matches,
        "decisive_matches": decisive_matches,
        "abandoned_count": abandoned_count,
        "containment_rate": round(defender_wins / decisive_matches, 4) if decisive_matches else 0.0,
        "attacker_win_rate": round(attacker_wins / decisive_matches, 4) if decisive_matches else 0.0,
        "avg_resolution_minutes": (
            round(sum(resolution_minutes) / len(resolution_minutes), 2) if resolution_minutes else None
        ),
    }
    if archetype_key is not None:
        bucket = {"archetype_key": archetype_key, **bucket}
    return bucket


@router.get("/public/stats/global-index")
async def get_global_index_stats(db: AsyncSession = Depends(get_db)):
    """The "Global Incident Response Index" — no auth. Per-archetype_key
    containment rate / attacker-win rate / avg time-to-resolution, plus an
    `overall` bucket aggregated across every archetype. Cohort counts/rates
    only; never a user_id, match_id, or any per-match record."""
    cached = _GLOBAL_INDEX_CACHE.get("global-index")
    if cached is not None:
        return cached

    result = await db.execute(
        select(
            ArenaMatch.archetype_key,
            ArenaMatch.status,
            ArenaMatch.started_at,
            ArenaMatch.completed_at,
        ).where(
            ArenaMatch.completed_at.isnot(None),
            ArenaMatch.status.in_(_COMPLETED_STATUSES),
        )
    )
    rows = result.all()

    by_archetype: dict[str, list] = {}
    for row in rows:
        by_archetype.setdefault(row.archetype_key, []).append(row)

    payload = {
        "overall": _compute_archetype_bucket(None, rows),
        "archetypes": [
            _compute_archetype_bucket(key, archetype_rows)
            for key, archetype_rows in sorted(by_archetype.items())
        ],
        "generated_at": datetime.utcnow().isoformat(),
        "cache_ttl_seconds": _GLOBAL_INDEX_CACHE.ttl_seconds,
    }
    _GLOBAL_INDEX_CACHE.set("global-index", payload)
    return payload


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
    event_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Join the PvP matchmaking queue. Idempotent — calling this again while
    already queued (or already matched but not yet polled) just returns the
    current state instead of creating a duplicate entry.

    Live Breach Events Phase 4: pass `?event_id=...` to join that event's
    OWN pool instead of the ad-hoc pool — pairing is then scoped only
    against other players queued for the same event, and the resulting
    match uses the event's fixed seed/archetype_key/difficulty. 404 if
    `event_id` doesn't exist; 400 if the event has been cancelled.
    """
    try:
        return await arena_matchmaking_service.join_queue(db, current_user.id, event_id=event_id)
    except arena_matchmaking_service.EventNotFoundError:
        raise HTTPException(status_code=404, detail="Arena event not found")
    except arena_matchmaking_service.EventNotJoinableError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ── Live Breach Events Phase 4: scheduled synchronized live events ─────────
#
# GET /arena/events/{id}/status — deliberately NO AUTH, same reasoning as
# Phase 1's public replay route and Phase 3's public global-index: the
# plan's own framing of the frontend's ArenaEventsPage.tsx explicitly calls
# an event's live leaderboard/ticker "public-readable, itself good
# shareable content" — that's the whole growth-loop point of this feature,
# so gating it behind auth would work against it. Contrast with
# GET /arena/matches/{id}, which stays participant-only: that route exposes
# a specific in-progress match's live, possibly-still-secret org state. This
# route only ever returns aggregate counts plus already-decided (terminal)
# match outcomes — nothing live-and-hidden about any one player's state.
#
# Leaderboard definition (documented here, matching the public-stats
# section's precedent for writing the rationale down rather than just the
# code): one entry per DECISIVE match in the event (status in
# attacker_won/defender_won — an abandoned match has no winner to rank,
# same "decisive" convention _compute_archetype_bucket already uses),
# representing the WINNING side only, sorted fastest-win-first by
# resolution_seconds (completed_at - started_at). This is the simplest
# coherent "cohort leaderboard" given what's on ArenaMatch already, without
# reimplementing Phase I's separate ELO system (arena_rating_service.py) —
# ELO still updates normally and independently for every event match
# exactly like any other match; this leaderboard is a per-event view only.

def _event_leaderboard_entry(match: ArenaMatch, users_by_id: dict) -> Optional[dict]:
    if match.status not in _STATS_DECISIVE_STATUSES:
        return None
    if not match.started_at or not match.completed_at:
        # Same "skip, never treat as 0-minute" rule the public stats bucket uses.
        return None

    winner_is_attacker = match.status == "attacker_won"
    winner_user_id = match.attacker_user_id if winner_is_attacker else match.defender_user_id
    user = users_by_id.get(winner_user_id) if winner_user_id else None
    # This route is public/no-auth (see section comment above) — never echo
    # a raw email address here. Reuse Phase 1's opt-in public-label pattern
    # (_public_participant_label, above): a winner's opted-in display handle
    # if set, otherwise a generic non-identifying placeholder.
    display_name = _public_participant_label(user, "Player") if user else "AI Bot"
    resolution_seconds = (match.completed_at - match.started_at).total_seconds()

    return {
        "match_id": match.id,
        "user_id": winner_user_id,
        "display_name": display_name,
        "won": True,
        "winner_role": "attacker" if winner_is_attacker else "defender",
        "resolution_seconds": round(resolution_seconds, 1),
    }


@router.get("/events")
async def list_public_arena_events(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Public, no-auth browse listing for ArenaEventsPage.tsx (frontend
    "browse upcoming/live/past" per the Phase 4 plan). `GET /admin/arena/events`
    (admin.py) already lists every event, but it's gated behind `require_admin`
    and can't serve a public browse page — this route is the minimal
    read-only counterpart, mirroring the same no-auth precedent already
    established by `GET /arena/public/replay/{token}` and
    `GET /arena/public/stats/global-index` above: no per-user data, no
    mutation, just `arena_event_summary()` (the same serializer the admin
    route and `GET /arena/events/{id}/status` both already use, so the three
    never drift on shape).

    Optional `?status=` filter (scheduled/live/completed/cancelled); results
    are newest-`starts_at`-first, capped at 100 per page.
    """
    limit = max(1, min(limit, 100))
    query = select(ArenaEvent).order_by(desc(ArenaEvent.starts_at)).limit(limit)
    if status is not None:
        if status not in ("scheduled", "live", "completed", "cancelled"):
            raise HTTPException(status_code=400, detail="Invalid status filter")
        query = query.where(ArenaEvent.status == status)
    result = await db.execute(query)
    events = result.scalars().all()
    return [arena_event_summary(e) for e in events]


@router.get("/events/{event_id}/status")
async def get_arena_event_status(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """{event, joined_count, matches, leaderboard} for a scheduled
    synchronized event. No auth (see section comment above).

    Opportunistically drains the AI-fallback-fill for this event
    (`arena_matchmaking_service.fill_unmatched_event_queue_with_ai`) once
    its join window has closed (`event.status != "scheduled"`) — this
    endpoint runs in the `backend` (uvicorn) process, the one that actually
    owns `app.websocket.manager.manager`'s in-memory queue, and the plan's
    own frontend convention has clients poll this exact endpoint while an
    event is live, so it's the natural, always-correct-process place to do
    it. See app/services/arena_event_service.py's module docstring for why
    the Celery Beat transition task deliberately does NOT do this itself.
    No-op once this event's queue is already empty.

    `joined_count` = distinct humans who have engaged with this event at
    all: everyone already paired into a match under this event (attacker or
    defender side, excluding the null/bot side) PLUS anyone still waiting
    in the in-process queue for this event who hasn't been paired yet.
    """
    event_result = await db.execute(select(ArenaEvent).where(ArenaEvent.id == event_id))
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Arena event not found")

    if event.status != "scheduled":
        await arena_matchmaking_service.fill_unmatched_event_queue_with_ai(db, event_id)

    matches_result = await db.execute(
        select(ArenaMatch).where(ArenaMatch.event_id == event_id).order_by(ArenaMatch.created_at)
    )
    matches = matches_result.scalars().all()

    matched_user_ids = set()
    for m in matches:
        if m.attacker_user_id:
            matched_user_ids.add(m.attacker_user_id)
        if m.defender_user_id:
            matched_user_ids.add(m.defender_user_id)

    waiting_count = sum(
        1
        for entry in manager.arena_queue.values()
        if entry.get("event_id") == event_id and entry["matched_match_id"] is None
    )
    joined_count = len(matched_user_ids) + waiting_count

    winner_user_ids = {
        (m.attacker_user_id if m.status == "attacker_won" else m.defender_user_id)
        for m in matches
        if m.status in _STATS_DECISIVE_STATUSES
    }
    winner_user_ids.discard(None)
    users_by_id = {}
    if winner_user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(winner_user_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    leaderboard = sorted(
        (
            entry
            for entry in (_event_leaderboard_entry(m, users_by_id) for m in matches)
            if entry is not None
        ),
        key=lambda e: e["resolution_seconds"],
    )

    return {
        "event": arena_event_summary(event),
        "joined_count": joined_count,
        "matches": [_match_summary(m) for m in matches],
        "leaderboard": leaderboard,
    }
