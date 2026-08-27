"""
Phase 2 — Action console core loop: the in-process live-run store.

BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4 / docs/PHASE2_KICKOFF.md Part B,
Item 3. `verb_engine.RunState` is server-only and never persisted mid-run —
per app/models/action_run.py's docstring, `ActionRun` is written exactly
once, at `run.end`. Something has to hold the live `RunState` across the
many WebSocket messages between "run started" and "run ended", the same way
`app.websocket.manager.ConnectionManager` holds live Arena/simulation state
in-process rather than round-tripping through the DB on every message. This
module is that something, plus its lifecycle: eviction/persistence on a
normal end, a sweep for abandoned runs, and reconnect support.

Two clocks, tracked separately, on purpose:
  - `RunState.elapsed_seconds` (verb_engine) — the GAME clock. Advances only
    by a verb's fixed cost; it is what drives attacker stage progression and
    what "the mode's time cap" is measured against (spending the whole
    budget on verbs, not sitting idle, per spec section 0.1's caps).
  - `LiveRun.real_started_at` (this module) — a REAL wall-clock server
    timestamp. Never influenced by anything in a client message (the client
    only ever sends `{"verb", "target"}` — see the WS handler — so there is
    nothing for a client to lie about here). Used ONLY to detect
    abandonment: a run whose game clock is barely ticking because the
    player simply stopped sending messages would never trip the game-clock
    cap on its own, so `sweep_expired` compares REAL elapsed time instead.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.scenario import Scenario
from app.services import dossier_service
from app.services import verb_engine
from app.services.action_engine import CompiledRun
from app.services.action_run_share import freeze_public_snapshot
from app.services.ghost_race_beat import maybe_record_ghost_race_beat
from app.services.technique_dossier import TECHNIQUE_DOSSIER
from app.services.xp_service import award_xp, check_scenario_achievements

logger = logging.getLogger(__name__)

# Session-length caps, spec section 0.1 ("Non-negotiable constraints"):
# teaser 60-90s hard cap (90 used here — the no-auth landing teaser itself
# is a separate system, TeaserEvent/teaser.py, not this store; this entry
# exists for when/if a teaser-flavored action run is wired to it), Daily
# Breach 8 minutes max, full scenarios default to the 10-minute compressed
# mode for individual users. Org tabletop sessions are a completely
# different system (SimulationSession/simulation_ws_handler) and never
# reach this store at all.
CAP_SECONDS_BY_MODE: dict[str, int] = {
    "teaser": 90,
    "daily": 8 * 60,
    "scenario": 10 * 60,
}

# "force-finalizes any run whose elapsed time has passed the mode's cap
# plus a 60s grace" — the grace absorbs normal WS round-trip latency around
# the exact cap boundary so a run isn't swept out from under a client that
# was still mid-flight on its last legitimate action.submit.
SWEEP_GRACE_SECONDS = 60

# XP is score-derived and deliberately simple/provisional, matching
# verb_engine's own UNWARRANTED_NOTIFICATION_PENALTY/PRECISION_PENALTY
# framing — a real balancing pass is a later item, not this one.
XP_PER_SCORE_POINT_DIVISOR = 10


@dataclass
class LiveRun:
    run_id: str
    user_id: Optional[str]
    scenario_id: str
    mode: str
    run_state: verb_engine.RunState
    # Set only for mode="daily" runs — carried through to the persisted
    # ActionRun row in finalize() (migration 0030's daily_challenge_id).
    daily_challenge_id: Optional[str] = None
    # Phase 4 ghost racing — opponent ActionRun.id when this live run was
    # started via POST /action-runs/race. Used at finalize() to detect beats.
    ghost_opponent_run_id: Optional[str] = None
    real_started_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def cap_seconds(self) -> int:
        return CAP_SECONDS_BY_MODE[self.mode]


class ActionRunStore:
    """In-process, single-backend-process live state — the same scoping
    assumption `ConnectionManager` already makes for Arena/simulation
    presence, and for the same reason: only this process holds it, so it
    must run inside the `backend` uvicorn process (see main.py's
    `_arena_event_queue_sweep_loop` for the established precedent this
    module's sweep loop follows)."""

    def __init__(self) -> None:
        self._runs: dict[str, LiveRun] = {}
        self._lock = asyncio.Lock()

    async def start_run(
        self, run_id: str, user_id: Optional[str], scenario_id: str, mode: str, compiled: CompiledRun,
        daily_challenge_id: Optional[str] = None,
        ghost_opponent_run_id: Optional[str] = None,
    ) -> LiveRun:
        live = LiveRun(
            run_id=run_id,
            user_id=user_id,
            scenario_id=scenario_id,
            mode=mode,
            run_state=verb_engine.new_run(compiled),
            daily_challenge_id=daily_challenge_id,
            ghost_opponent_run_id=ghost_opponent_run_id,
        )
        async with self._lock:
            self._runs[run_id] = live
        return live

    async def get(self, run_id: str) -> Optional[LiveRun]:
        """Used by the WS handler on connect to decide fresh-start vs
        resume — reconnecting to a `run_id` that's already live must
        resume the stored RunState, never error, per the Item 3 spec."""
        async with self._lock:
            return self._runs.get(run_id)

    async def find_live_daily_run(self, user_id: str, daily_challenge_id: str) -> Optional[LiveRun]:
        """Look up an IN-PROGRESS daily run for (user_id, daily_challenge_id).

        A row in `action_runs` exists only once `finalize()` commits it
        (per `ActionRun`'s docstring — written exactly once, at run.end); a
        run that's still being played lives solely here. `POST
        /daily/action-run`'s persisted-row pre-check is therefore blind to
        a run already in progress — this is what lets it detect one, so a
        double-tap/refresh resumes the existing run_id instead of starting
        a second live run for the same (user, challenge) that would later
        crash its own finalize() on `uq_action_run_daily_challenge_user`."""
        async with self._lock:
            for live in self._runs.values():
                if live.user_id == user_id and live.daily_challenge_id == daily_challenge_id:
                    return live
        return None

    async def apply_verb(self, run_id: str, verb: str, target: Optional[str]) -> tuple[verb_engine.VerbResult, bool]:
        """Applies one verb to the live run and returns (result, is_over).
        Raises KeyError if run_id isn't live (caller's job to have already
        confirmed it is, via `get`/`start_run`)."""
        async with self._lock:
            live = self._runs[run_id]
            result = verb_engine.apply_verb(live.run_state, verb, target)
            if result.error is None:
                live.run_state = result.run
                live.last_activity_at = datetime.utcnow()
            is_over = verb_engine.is_run_over(live.run_state, live.cap_seconds)
            return result, is_over

    async def _scenario_title(self, db: AsyncSession, scenario_id: str) -> str:
        result = await db.execute(select(Scenario.title).where(Scenario.id == scenario_id))
        title = result.scalar_one_or_none()
        return title or ""

    def _techniques_encountered_summary(self, technique_ids: frozenset) -> list[dict]:
        """This run's `encountered_technique_ids` shaped for the run.end
        debrief — {technique_id, name, description} only, no
        incident_narrative/source_reference/scenarios (that's the full
        Dossier page's job, via GET /dossier/me, not a per-run summary).
        Unlike `_record_technique_encounters`, this runs regardless of
        `live.user_id` — an unauthenticated teaser run still fired these
        stages and the player should still see what they encountered, even
        though nothing gets persisted to their (nonexistent) dossier."""
        return [
            {
                "technique_id": technique_id,
                "name": TECHNIQUE_DOSSIER[technique_id]["name"],
                "description": TECHNIQUE_DOSSIER[technique_id]["description"],
            }
            for technique_id in sorted(technique_ids)
            if technique_id in TECHNIQUE_DOSSIER
        ]

    async def finalize(
        self, db: AsyncSession, run_id: str, forced_outcome: Optional[str] = None,
    ) -> Optional[dict]:
        """Persist the ActionRun row exactly once, award XP, check
        achievements, and evict the run from the live store. `forced_outcome`
        is set by `sweep_expired` for abandoned runs ("...as outcome=breached");
        a normal end (the player played it out, or the cap fired mid-loop)
        determines its own outcome via verb_engine.determine_outcome.
        Returns a summary dict for the caller to build the run.end broadcast
        from, or None if run_id wasn't live (e.g. a race with another
        finalize — evicted exactly once, safe to call defensively)."""
        async with self._lock:
            live = self._runs.pop(run_id, None)
        if live is None:
            return None

        run_state = live.run_state
        outcome = forced_outcome or verb_engine.determine_outcome(run_state)
        score_breakdown = verb_engine.compute_score(run_state, outcome, live.cap_seconds)

        # Frozen here, on the authenticated finalize path, so the public
        # GET never has to compile/replay a seed. Built from the live
        # RunState (already fog-gated) rather than from the persisted
        # action_log + seed, which would re-introduce the seed onto a
        # code path that later gets copied onto the unauthenticated route.
        action_run = ActionRun(
            # Deliberately the SAME id `run_id` has meant since POST
            # /action-runs minted it (the live-store key, the /ws/run/{id}
            # URL) — not ActionRun.id's own uuid4 default. Before this, the
            # persisted row got a second, independently-generated id that
            # only ever surfaced in the run.end WS event's action_run_id
            # field, with nothing in the initial POST /action-runs response
            # hinting a second id existed — a real trap (see
            # app/api/routes/action_runs.py's response, which now returns
            # both fields with the same value under their true names).
            # Unifying them removes the trap structurally instead of just
            # documenting it.
            id=live.run_id,
            user_id=live.user_id,
            scenario_id=live.scenario_id,
            daily_challenge_id=live.daily_challenge_id,
            seed=run_state.compiled.seed,
            mode=live.mode,
            action_log=list(run_state.action_log),
            score_breakdown=score_breakdown,
            total_score=score_breakdown["total_score"],
            duration_seconds=run_state.elapsed_seconds,
            outcome=outcome,
            public_snapshot=freeze_public_snapshot(run_state),
        )
        db.add(action_run)
        await db.flush()  # assigns action_run.id; visible to this same transaction's own queries below

        if live.user_id and run_state.encountered_technique_ids:
            await dossier_service.record_technique_encounters(
                db, live.user_id, run_state.encountered_technique_ids,
            )

        xp_awarded = 0
        new_achievements: list[str] = []
        # Proportionate Response XP/achievement gate, keyed on the named
        # outcome rather than raw score. Deliberate, not derivable from the
        # score alone: `contained` earns full credit, `contained_at_cost`
        # earns half (still stopped the attacker, but not cleanly), and
        # every other state — `overreacted` included — earns NOTHING, no
        # achievements. The XP cliff sits between imprecise and reckless,
        # not between perfect and imperfect: a `contained_at_cost` run
        # still earns credit for stopping the attacker, while `overreacted`
        # did not act like an incident responder (isolated most of the
        # network to be safe) and earns nothing for it, even though the
        # final target was technically stopped. This is what actually
        # closes the "isolate everything" exploit the whole spec exists to
        # fix — a raw-score-only gate would still let a big, imprecise
        # score buy XP.
        if live.user_id and outcome in ("contained", "contained_at_cost"):
            xp_amount = max(0, score_breakdown["total_score"] // XP_PER_SCORE_POINT_DIVISOR)
            if outcome == "contained_at_cost":
                xp_amount //= 2
            if xp_amount > 0:
                xp_result = await award_xp(
                    db, live.user_id, xp_amount, "action_run",
                    f"Action run — {outcome}", source_id=action_run.id,
                )
                xp_awarded = xp_result.get("amount", 0)

            completed_count = await db.scalar(
                select(func.count()).select_from(ActionRun).where(ActionRun.user_id == live.user_id)
            )
            # check_scenario_achievements (app.services.xp_service) has no
            # other caller anywhere in the backend today (confirmed by
            # repo-wide search) — this is genuinely its first real caller.
            # Only called for contained/contained_at_cost — an overreacted
            # or breached run has nothing worth checking achievements
            # against per the gate above.
            new_achievements = await check_scenario_achievements(
                db, live.user_id,
                scenario_title=await self._scenario_title(db, live.scenario_id),
                score_pct=score_breakdown["score_pct"],
                time_seconds=run_state.elapsed_seconds,
                total_completed=completed_count or 0,
            )

        if live.ghost_opponent_run_id and live.user_id:
            await maybe_record_ghost_race_beat(
                db,
                ghost_opponent_run_id=live.ghost_opponent_run_id,
                racer_user_id=live.user_id,
                racer_action_run_id=action_run.id,
                racer_outcome=outcome,
                racer_duration_seconds=run_state.elapsed_seconds,
            )

        await db.commit()

        return {
            "action_run_id": action_run.id,
            "outcome": outcome,
            "score_breakdown": score_breakdown,
            "xp_awarded": xp_awarded,
            "new_achievements": new_achievements,
            "techniques_encountered": self._techniques_encountered_summary(run_state.encountered_technique_ids),
        }

    async def sweep_expired(self, db: AsyncSession) -> list[tuple[str, dict]]:
        """Force-finalizes every run whose REAL elapsed time has passed its
        mode's cap plus SWEEP_GRACE_SECONDS, as outcome="breached" — abandoned
        runs (the player closed the tab and never sent another
        action.submit) must still produce an ActionRun row, both for
        funnel data and so a ghost exists for Phase 4.

        For mode="daily" runs, also routes the finalized result through
        `record_daily_action_run_result` exactly like
        `action_run_ws_handler`'s own is_over branch does (merged into the
        returned summary) — a player swept for abandonment still gets
        streak/rank credit instead of silently losing it. Imported lazily
        to avoid a circular import: app.api.routes.daily imports
        action_run_store at module level.

        Returns (run_id, summary) pairs for every run actually finalized
        this sweep — `summary` is finalize()'s dict (plus the daily
        carry-over fields when applicable), the same shape
        `build_run_end_event` expects. The caller (main.py's sweep loop)
        uses this to broadcast run.end to whichever socket, if any, is
        still connected — a connected-but-slow player whose run gets swept
        must still receive their debrief instead of a dead socket."""
        from app.api.routes.daily import record_daily_action_run_result

        now = datetime.utcnow()
        async with self._lock:
            expired = [
                (run_id, live) for run_id, live in self._runs.items()
                if (now - live.real_started_at).total_seconds() > live.cap_seconds + SWEEP_GRACE_SECONDS
            ]

        finalized: list[tuple[str, dict]] = []
        for run_id, live in expired:
            try:
                summary = await self.finalize(db, run_id, forced_outcome="breached")
                if summary is None:
                    continue
                if live.mode == "daily" and live.daily_challenge_id and live.user_id:
                    daily_summary = await record_daily_action_run_result(
                        db, live.daily_challenge_id, live.user_id,
                        summary["score_breakdown"]["total_score"],
                    )
                    summary = {**summary, **daily_summary}
                finalized.append((run_id, summary))
            except Exception:
                # One bad run must never kill the sweep for the rest —
                # mirrors main.py's _arena_event_queue_sweep_loop precedent.
                logger.exception("action run sweep failed to finalize run_id=%s", run_id)
        return finalized


# Process-wide singleton — mirrors app.websocket.manager's module-level
# `manager` instance (the WS handler/route layer imports this the same way).
action_run_store = ActionRunStore()
