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
  POST /action-runs/{id}/share                    — auth, owner-only, mints token + text card
  GET  /action-runs/public/replay/{token}         — no auth, redacted DTO
  GET  /action-runs/public/replay/{token}/card.png — no auth, Pillow OG image
  GET  /action-runs/public/unfurl/{token}         — no auth, crawler HTML with og:image

Phase 4 ghost racing (selection + server-controlled DTO, not action_log
passthrough — see action_run_ghost.py / spec §6 correction):
  GET  /action-runs/public/ghost/{token}          — no auth, Race-this-run DTO
  POST /action-runs/race                          — auth, start scenario run on ghost seed
"""
import html
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, limiter
from app.db.session import get_db
from app.models.action_run import ActionRun
from app.models.scenario import Scenario
from app.models.user import User
from app.services import action_engine
from app.services.action_run_ghost import (
    build_ghost_dto,
    resolve_ghost_by_share_token,
)
from app.services.action_run_share import (
    SHARE_URL_PREFIX,
    SHAREABLE_MODES,
    public_player_label,
    resolve_public_replay,
    share_card_extras,
)
from app.services.action_run_share_card import build_share_card_text, render_share_card_png
from app.services.action_run_store import CAP_SECONDS_BY_MODE, action_run_store

router = APIRouter(prefix="/action-runs", tags=["action-runs"])


class ActionRunCreateRequest(BaseModel):
    scenario_id: str


class RaceStartRequest(BaseModel):
    """Start a same-seed practice race against a completed ghost run.

    Exactly one of ghost_run_id / share_token. Seed is looked up server-side
    from the ActionRun row — never accepted from the client (ghost DTOs
    deliberately omit seed).
    """
    ghost_run_id: Optional[str] = None
    share_token: Optional[str] = None


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_action_run(
    request: Request,
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


@router.post("/race", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def start_ghost_race(
    request: Request,
    payload: RaceStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 4 — start a live scenario-mode run on a ghost's seed.

    After Daily finishes, a second Daily attempt is impossible (409); racing
    the analyst above you is a practice run on that ghost's identical seed
    (mode=scenario, no daily_challenge_id). "Race this run" from a share
    link uses the same path via share_token.

    Returns the new run_id plus the locked ghost DTO (seed never on the
    ghost object) so the client can mount GhostPlayback without a second
    round-trip that might re-select a different Daily ghost.
    """
    has_id = bool(payload.ghost_run_id)
    has_token = bool(payload.share_token)
    if has_id == has_token:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of ghost_run_id or share_token",
        )

    if payload.share_token:
        ghost_row = await db.scalar(
            select(ActionRun).where(ActionRun.share_token == payload.share_token)
        )
    else:
        ghost_row = await db.scalar(
            select(ActionRun).where(ActionRun.id == payload.ghost_run_id)
        )

    if ghost_row is None or ghost_row.mode not in SHAREABLE_MODES:
        raise HTTPException(status_code=404, detail="Ghost not found")
    if not ghost_row.outcome or ghost_row.duration_seconds is None:
        raise HTTPException(status_code=404, detail="Ghost not found")

    scenario = await db.scalar(select(Scenario).where(Scenario.id == ghost_row.scenario_id))
    if scenario is None or scenario.status != "approved":
        raise HTTPException(status_code=404, detail="Scenario not found")

    player_user = None
    if ghost_row.user_id:
        player_user = await db.scalar(select(User).where(User.id == ghost_row.user_id))

    # Daily ghosts stay map-state-only; scenario share races may include targets.
    include_targets = ghost_row.mode == "scenario"
    if payload.share_token:
        identity = "share_token"
        share_token = payload.share_token
    else:
        # Auth Daily path — ghost_run_id identity on the DTO.
        identity = "ghost_run_id"
        share_token = ghost_row.share_token

    ghost_dto = build_ghost_dto(
        ghost_row,
        scenario=scenario,
        player_label=public_player_label(player_user),
        include_targets=include_targets,
        identity=identity,
        share_token=share_token,
    )
    if ghost_dto is None:
        raise HTTPException(status_code=404, detail="Ghost not found")

    # Seed stays server-side until this create response for the racer's own run.
    seed = ghost_row.seed
    compiled = action_engine.compile_scenario(scenario, seed)
    run_id = str(uuid.uuid4())
    mode = "scenario"
    await action_run_store.start_run(run_id, current_user.id, scenario.id, mode, compiled)

    return {
        "run_id": run_id,
        "action_run_id": run_id,
        "scenario_id": scenario.id,
        "seed": seed,
        "mode": mode,
        "cap_seconds": CAP_SECONDS_BY_MODE[mode],
        "ghost": ghost_dto,
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


async def _share_response(db: AsyncSession, action_run, share_token: str) -> dict:
    extras = await share_card_extras(db, action_run)
    scenario_title = ""
    title = await db.scalar(select(Scenario.title).where(Scenario.id == action_run.scenario_id))
    if title:
        scenario_title = title
    return {
        "share_token": share_token,
        "share_url_path": f"{SHARE_URL_PREFIX}/{share_token}",
        "share_card": build_share_card_text(
            scenario_title=scenario_title,
            outcome=action_run.outcome,
            score=action_run.total_score,
            duration_seconds=action_run.duration_seconds,
            share_token=share_token,
            mode=action_run.mode,
            challenge_number=extras["challenge_number"],
            streak=extras["streak"],
        ),
    }


def _og_image_url(share_token: str) -> str:
    origin = settings.FRONTEND_URL.rstrip("/")
    return f"{origin}/api/v1/action-runs/public/replay/{share_token}/card.png"


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
        return await _share_response(db, action_run, action_run.share_token)

    locked_result = await db.execute(
        select(ActionRun).where(ActionRun.id == run_id).with_for_update()
    )
    action_run = locked_result.scalar_one_or_none()
    if action_run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if action_run.share_token:
        return await _share_response(db, action_run, action_run.share_token)

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
                return await _share_response(db, action_run, action_run.share_token)
    else:
        raise HTTPException(status_code=500, detail="Could not generate a unique share token")

    return await _share_response(db, action_run, action_run.share_token)


@router.get("/public/replay/{share_token}/card.png")
@limiter.limit("30/minute")
async def get_public_share_card_png(
    request: Request,
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """OG image for `/r/{token}`. Built from the same locked DTO as the
    JSON GET — never from seed / action_log / a poisoned snapshot's extra
    keys. Invalid tokens 404 identically to the JSON route."""
    dto = await resolve_public_replay(db, share_token)
    if dto is None:
        raise HTTPException(status_code=404, detail="Replay not found")
    png = render_share_card_png(dto)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/public/unfurl/{share_token}", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def get_public_share_unfurl(
    request: Request,
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Crawler-facing HTML (Slack/iMessage/Twitter). nginx rewrites bot
    hits on `/r/{token}` here so og:image is in the first response, not
    only in the SPA's JS-set meta tags. 404s the same as the JSON GET."""
    dto = await resolve_public_replay(db, share_token)
    if dto is None:
        raise HTTPException(status_code=404, detail="Replay not found")
    title = html.escape(f"{dto['scenario_title']} — {dto['outcome']}")
    description = html.escape(
        f"{dto['score']:,} pts · {dto['duration_seconds']}s · {dto['mode']}"
    )
    image = html.escape(_og_image_url(share_token))
    page = html.escape(f"{settings.FRONTEND_URL.rstrip('/')}{SHARE_URL_PREFIX}/{share_token}")
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<meta name="description" content="{description}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{description}"/>
<meta property="og:type" content="website"/>
<meta property="og:image" content="{image}"/>
<meta property="og:url" content="{page}"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{title}"/>
<meta name="twitter:description" content="{description}"/>
<meta name="twitter:image" content="{image}"/>
<link rel="canonical" href="{page}"/>
</head>
<body><a href="{page}">Open replay</a></body>
</html>"""
    )


@router.get("/public/replay/{share_token}")
@limiter.limit("60/minute")
async def get_public_action_replay(
    request: Request,
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public, no-auth Action Console run replay. Hard-gated to a frozen
    public_snapshot + shareable mode as defense-in-depth (a token is only
    ever minted for a completed daily/scenario run, but this route never
    trusts that alone). Missing, teaser, and snapshot-less tokens all
    404 identically — never 400, never a partial body.
    """
    dto = await resolve_public_replay(db, share_token)
    if dto is None:
        raise HTTPException(status_code=404, detail="Replay not found")
    return dto


@router.get("/public/ghost/{share_token}")
@limiter.limit("60/minute")
async def get_public_ghost(
    request: Request,
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Phase 4 — 'Race this run' from a public `/r/{token}` link.

    No auth (same entry pattern as public replay). Server-controlled ghost
    DTO: scenario-mode includes per-verb targets; daily-mode stays
    map-state-only (shared-seed spoiler bar). Missing / teaser / unsourced
    tokens 404 identically — never a raw action_log body.
    """
    dto = await resolve_ghost_by_share_token(db, share_token)
    if dto is None:
        raise HTTPException(status_code=404, detail="Ghost not found")
    return dto

