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
"""
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.scenario import Scenario
from app.models.user import User
from app.services import action_engine
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
