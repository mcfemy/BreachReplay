"""
Phase 2 — Action console core loop: REST creation endpoint.

BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4 / docs/PHASE2_KICKOFF.md Part B,
Item 3. Mirrors sessions.py's `POST /sessions` (create-before-WS-takes-over)
and arena.py's `POST /matches` (secrets.randbelow seed choice) conventions:
a run_id is minted here, the scenario is compiled and registered live in
`action_run_store`, and the client then connects to
`/ws/run/{run_id}` to actually play it.

Mode is hardcoded to "scenario" here. Daily Breach's shared-seed creation
path (same scenario + same seed for every player that day) is
`POST /daily/action-run` (Item 4, backend/app/api/routes/daily.py) — it
calls the same `action_run_store.start_run()` with a deterministic seed
and a `daily_challenge_id` instead of a random one; nothing here needed
to change for that.

Public share links (opaque token, never a raw run_id) live on this same
router, mirroring Arena:
  POST /action-runs/{id}/share              — auth, owner-only, terminal row
  GET  /action-runs/public/replay/{token}   — no auth, redacted DTO only
"""
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.action_run import ActionRun
from app.models.scenario import Scenario
from app.models.user import User
from app.services import action_engine
from app.services.action_run_share import (
    SHARE_URL_PREFIX,
    SHAREABLE_MODES,
    build_public_replay_dto,
    public_player_label,
)
from app.services.action_run_store import CAP_SECONDS_BY_MODE, action_run_store

router = APIRouter(prefix="/action-runs", tags=["action-runs"])


class ActionRunCreateRequest(BaseModel):
    scenario_id: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_action_run(
    payload: ActionRunCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Scenario).where(Scenario.id == payload.scenario_id, Scenario.status == "approved")
    )
    scenario = result.scalar_one_or_none()
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # secrets.randbelow: non-deterministic seed CHOICE is intentional and
    # safe here — mirrors arena.py's create_match — never inside
    # action_engine.py's own compile_scenario, which must stay deterministic
    # given a seed (same seed, same run, which Phase 4 ghosts depend on).
    seed = secrets.randbelow(2**31 - 1)
    compiled = action_engine.compile_scenario(scenario, seed)

    run_id = str(uuid.uuid4())
    mode = "scenario"
    await action_run_store.start_run(run_id, current_user.id, scenario.id, mode, compiled)

    return {
        # The live-store key AND the WS connection id (/ws/run/{run_id}) —
        # use this to play the run.
        "run_id": run_id,
        # The ActionRun row's eventual primary key, for anything that
        # references the FINISHED run afterward (CMMC evidence-session
        # designation, GET /cmmc/client-orgs/{id}/runs, etc). Deliberately
        # the SAME value as run_id (action_run_store.finalize() persists
        # the row under this exact id) — returned under its own name here
        # so a caller never has to discover the run.end WS event's
        # action_run_id field is "the real id" the hard way.
        "action_run_id": run_id,
        "scenario_id": scenario.id,
        "seed": seed,
        "mode": mode,
        "cap_seconds": CAP_SECONDS_BY_MODE[mode],
    }


# ── Public share links (Arena-parallel) ──────────────────────────────────────
#
# Any completed daily/scenario run can get a public, no-login URL. Two routes:
#   POST /action-runs/{run_id}/share              — auth, owner-only, mints token
#   GET  /action-runs/public/replay/{share_token}  — no auth, redacted DTO only
#
# Deliberately does NOT compile_scenario / apply_verb / replay a seed —
# public_snapshot is frozen at finalize (same reason Arena reads
# final_org_state_cache rather than calling replay() on a crawled endpoint).


def _share_response(share_token: str) -> dict:
    return {"share_token": share_token, "share_url_path": f"{SHARE_URL_PREFIX}/{share_token}"}


@router.post("/{run_id}/share")
async def share_action_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or idempotently return) a public share token for a
    completed Action Console run. ActionRun rows are written once at
    finalize — a live in-progress run has no row, so a missing row is
    404 (same as an unknown id). Do NOT consult action_run_store and
    return 400 "still in progress": that would distinguish live UUIDs
    from unknown ones on an authenticated guess."""
    result = await db.execute(select(ActionRun).where(ActionRun.id == run_id))
    action_run = result.scalar_one_or_none()
    if action_run is None or action_run.user_id is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if action_run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this run")
    # Teaser / pre-0041 rows / missing freeze: not shareable. 404, not 400
    # — a 400 "this run exists but isn't ready" is an existence leak for
    # ids the caller shouldn't learn anything about beyond owner-403.
    if action_run.mode not in SHAREABLE_MODES or not isinstance(action_run.public_snapshot, dict):
        raise HTTPException(status_code=404, detail="Run not found")

    if action_run.share_token:
        return _share_response(action_run.share_token)

    locked_result = await db.execute(
        select(ActionRun).where(ActionRun.id == run_id).with_for_update()
    )
    action_run = locked_result.scalar_one_or_none()
    if action_run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if action_run.share_token:
        return _share_response(action_run.share_token)

    # secrets.token_urlsafe(16) — same mint as arena share_token. Column is
    # unique; retry a handful of times on IntegrityError as defense-in-depth
    # (the row lock above is the primary concurrent-mint fix).
    for _ in range(5):
        candidate = secrets.token_urlsafe(16)
        action_run.share_token = candidate
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(ActionRun).where(ActionRun.id == run_id).with_for_update()
            )
            action_run = result.scalar_one_or_none()
            if action_run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            if action_run.share_token:
                return _share_response(action_run.share_token)
    else:
        raise HTTPException(status_code=500, detail="Could not generate a unique share token")

    return _share_response(action_run.share_token)


@router.get("/public/replay/{share_token}")
async def get_public_action_replay(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public, no-auth Action Console run replay. Hard-gated to a frozen
    public_snapshot + shareable mode as defense-in-depth (a token is only
    ever minted for a completed daily/scenario run, but this route never
    trusts that alone). Missing, teaser, and snapshot-less tokens all
    404 identically — never 400, never a partial body.

    Unauthenticated and currently un-rate-limited, same note as Arena's
    public GET: apply slowapi if this sees crawl volume.
    """
    result = await db.execute(select(ActionRun).where(ActionRun.share_token == share_token))
    action_run = result.scalar_one_or_none()
    if action_run is None:
        raise HTTPException(status_code=404, detail="Replay not found")

    scenario_title = ""
    scenario_result = await db.execute(select(Scenario.title).where(Scenario.id == action_run.scenario_id))
    title_row = scenario_result.scalar_one_or_none()
    if title_row:
        scenario_title = title_row

    player_user = None
    if action_run.user_id:
        user_result = await db.execute(select(User).where(User.id == action_run.user_id))
        player_user = user_result.scalar_one_or_none()

    dto = build_public_replay_dto(
        action_run,
        scenario_title=scenario_title,
        player_label=public_player_label(player_user),
    )
    if dto is None:
        # Non-shareable row that somehow has a token (teaser, missing
        # snapshot) — identical 404 to an unknown token, never a 400 that
        # would confirm the token was real.
        raise HTTPException(status_code=404, detail="Replay not found")
    return dto

