"""Phase 4 — Ghost racing: selection + server-controlled ghost DTOs.

Per BREACHREPLAY_GAME_OVERHAUL_SPEC.md §6 correction (PR #49): this is
NOT a raw `action_log` or live `state.delta` passthrough.

Two race types, two timeline shapes:

* **Daily** (shared seed via `_deterministic_daily_seed`): map-state-only
  frames + verb timeline WITHOUT targets. Showing isolate/block/reset
  targets mid-race would spoiler today's identical map/IOC layout.
* **Scenario** ("race this run" via share token): same map frames, plus
  per-verb `target` (racer opted into that completed run). Still excludes
  warranted / correct / on_attack_path / IOC bodies / seed / full
  score_breakdown — same bar as the public `/r/{token}` DTO (PR #41).

Identity on the wire also differs by entry point:
* Authenticated Daily selection may echo `ghost_run_id` (needed to start a
  later race session).
* Public share-token entry never echoes a raw ActionRun.id — only the
  opaque `share_token` (same discipline as the public replay DTO).

Map frames are rebuilt server-side by replaying `action_log` against the
row's seed (seed never leaves this module onto the DTO). Timeline entries
are key-locked picks from the log, never the log wholesale.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.daily_challenge import DailyChallenge
from app.models.scenario import Scenario
from app.models.user import User
from app.services import action_engine, verb_engine
from app.services.action_run_share import (
    PUBLIC_TIMELINE_KEYS,
    SHAREABLE_MODES,
    _pick,
    _redact_edge,
    _redact_host,
    _score_pct,
    public_player_label,
)

# Outcomes where the defender stopped the final target (beat-their-time
# comparison uses duration_seconds as containment_seconds).
_CONTAINED_OUTCOMES = frozenset({"contained", "contained_at_cost", "overreacted"})

_COMMON_GHOST_KEYS = frozenset({
    "race_type",
    "outcome",
    "score",
    "score_pct",
    "duration_seconds",
    "containment_seconds",
    "scenario_title",
    "mode",
    "player_label",
    "verb_timeline",
    "map_frames",
})

# Auth Daily selection — may carry ghost_run_id for a later race session.
DAILY_GHOST_DTO_KEYS = _COMMON_GHOST_KEYS | frozenset({"ghost_run_id"})

# Public token path — never a raw ActionRun.id.
PUBLIC_GHOST_DTO_KEYS = _COMMON_GHOST_KEYS | frozenset({"share_token"})

# Scenario timeline may add `target`; Daily must not.
SCENARIO_TIMELINE_KEYS = PUBLIC_TIMELINE_KEYS | frozenset({"target"})

GHOST_MAP_FRAME_KEYS = frozenset({"elapsed_seconds", "hosts", "edges"})

# Keys that must never appear anywhere in a ghost DTO (nested included).
# Mirrors test_action_run_public_share.FORBIDDEN_KEYS for judgment / hidden
# state. `target` is NOT listed here — Daily strips it from the timeline
# and asserts absence in tests; Scenario intentionally includes it.
GHOST_FORBIDDEN_KEYS = frozenset({
    "seed",
    "hidden_iocs",
    "matches_on",
    "incident_narrative",
    "source_reference",
    "warranted",
    "rationale",
    "basis",
    "email",
    "full_name",
    "user_id",
    "unpatched_cves",
    "edr_installed",
    "raw_log",
    "forensics",
    "correct",
    "on_attack_path",
    "action_log",
    "score_breakdown",
    "revealed_iocs",
    "notified_party_ids",
    "collateral",
    "notifications",
})

IdentityMode = Literal["ghost_run_id", "share_token"]


def _containment_seconds(action_run: ActionRun) -> Optional[int]:
    if action_run.outcome in _CONTAINED_OUTCOMES:
        return action_run.duration_seconds
    return None


def _redact_verb_timeline_entry(entry: Any, *, include_targets: bool) -> Optional[dict]:
    """Key-locked timeline row. Daily: no target/warranted/correct.
    Scenario: target allowed; judgment flags still stripped."""
    if not isinstance(entry, dict):
        return None
    keys = SCENARIO_TIMELINE_KEYS if include_targets else PUBLIC_TIMELINE_KEYS
    redacted = _pick(entry, keys)
    if "verb" not in redacted:
        return None
    return redacted


def _frame_from_run_state(run_state: verb_engine.RunState) -> dict:
    """Fog-gated hosts + edges at the current moment — same tier shape as
    the public snapshot / earned_state_snapshot, never IOCs or parties."""
    earned = verb_engine.earned_state_snapshot(run_state)
    hosts = [h for h in (_redact_host(h) for h in earned.get("hosts", [])) if h is not None]
    edges = [e for e in (_redact_edge(e) for e in earned.get("edges", [])) if e is not None]
    return {
        "elapsed_seconds": run_state.elapsed_seconds,
        "hosts": hosts,
        "edges": edges,
    }


def _build_map_frames(scenario: Scenario, action_run: ActionRun) -> list[dict]:
    """Replay action_log against the row's seed server-side. Seed is read
    here and never copied onto the returned frames/DTO."""
    compiled = action_engine.compile_scenario(scenario, action_run.seed)
    run_state = verb_engine.new_run(compiled)
    frames = [_frame_from_run_state(run_state)]

    for entry in action_run.action_log or []:
        if not isinstance(entry, dict):
            continue
        verb = entry.get("verb")
        if not isinstance(verb, str):
            continue
        # Pass target through for replay fidelity only — it never rides onto
        # Daily timeline output. apply_verb ignores target for scan_network.
        target = entry.get("target")
        if target is not None and not isinstance(target, str):
            target = None
        result = verb_engine.apply_verb(run_state, verb, target)
        if result.error is not None:
            # Skip invalid historical entries rather than aborting the whole
            # ghost (poisoned / pre-migration oddities). Timeline still
            # lists the verb; map just doesn't advance for that step.
            continue
        run_state = result.run
        frames.append(_frame_from_run_state(run_state))

    return frames


def build_ghost_dto(
    action_run: ActionRun,
    *,
    scenario: Scenario,
    player_label: str,
    include_targets: bool,
    identity: IdentityMode,
    share_token: Optional[str] = None,
) -> Optional[dict]:
    """Build a locked ghost DTO. Returns None when the row is not a valid
    ghost source (teaser, missing terminal fields, public path without token)."""
    if action_run.mode not in SHAREABLE_MODES:
        return None
    # ActionRun rows are only written at finalize — presence implies
    # terminal — but require outcome + duration as defense-in-depth against
    # a half-written test row.
    if not action_run.outcome or action_run.duration_seconds is None:
        return None

    verb_timeline = [
        e for e in (
            _redact_verb_timeline_entry(entry, include_targets=include_targets)
            for entry in (action_run.action_log or [])
        )
        if e is not None
    ]
    map_frames = _build_map_frames(scenario, action_run)

    dto = {
        "race_type": "scenario" if include_targets else "daily",
        "outcome": action_run.outcome,
        "score": action_run.total_score,
        "score_pct": _score_pct(action_run.score_breakdown),
        "duration_seconds": action_run.duration_seconds,
        "containment_seconds": _containment_seconds(action_run),
        "scenario_title": scenario.title or "",
        "mode": action_run.mode,
        "player_label": player_label,
        "verb_timeline": verb_timeline,
        "map_frames": map_frames,
    }

    if identity == "share_token":
        token = share_token or action_run.share_token
        if not token:
            return None
        dto["share_token"] = token
    else:
        dto["ghost_run_id"] = action_run.id

    return dto


async def select_daily_ghost_run(
    db: AsyncSession,
    *,
    daily_challenge_id: str,
    user_id: str,
) -> Optional[ActionRun]:
    """Default Daily ghost: the completed run just above `user_id` on
    today's action leaderboard (total_score DESC, duration ASC).

    * Caller already finished and is rank R>1 → ghost is rank R-1.
    * Caller is rank 1 → None (nobody above).
    * Caller has no terminal run yet → ghost is last place (the run an
      unranked player would place just above by entering the board).
    * Empty board → None.

    Only persisted ActionRun rows (finalize) are considered — live
    in-progress runs in action_run_store are invisible here by design.
    """
    result = await db.execute(
        select(ActionRun)
        .where(
            ActionRun.daily_challenge_id == daily_challenge_id,
            ActionRun.mode == "daily",
        )
        .order_by(desc(ActionRun.total_score), ActionRun.duration_seconds, ActionRun.created_at)
    )
    runs = list(result.scalars().all())
    if not runs:
        return None

    my_idx = next((i for i, r in enumerate(runs) if r.user_id == user_id), None)
    if my_idx is None:
        return runs[-1]
    if my_idx == 0:
        return None
    return runs[my_idx - 1]


async def resolve_daily_ghost(
    db: AsyncSession,
    *,
    user_id: str,
    daily_challenge_id: Optional[str] = None,
) -> Optional[dict]:
    """Auth Daily path: select ghost + build map-state-only DTO."""
    if daily_challenge_id is None:
        challenge = await db.scalar(
            select(DailyChallenge).where(DailyChallenge.challenge_date == date.today())
        )
    else:
        challenge = await db.scalar(
            select(DailyChallenge).where(DailyChallenge.id == daily_challenge_id)
        )
    if challenge is None:
        return None

    ghost = await select_daily_ghost_run(
        db, daily_challenge_id=challenge.id, user_id=user_id,
    )
    if ghost is None:
        return None

    scenario = await db.scalar(select(Scenario).where(Scenario.id == ghost.scenario_id))
    if scenario is None:
        return None

    player_user = None
    if ghost.user_id:
        player_user = await db.scalar(select(User).where(User.id == ghost.user_id))

    return build_ghost_dto(
        ghost,
        scenario=scenario,
        player_label=public_player_label(player_user),
        include_targets=False,
        identity="ghost_run_id",
    )


async def resolve_ghost_by_share_token(
    db: AsyncSession,
    share_token: str,
) -> Optional[dict]:
    """Public 'Race this run' path. Scenario-mode runs get targets;
    Daily-mode shared links stay map-state-only (same-seed spoiler bar)."""
    action_run = await db.scalar(
        select(ActionRun).where(ActionRun.share_token == share_token)
    )
    if action_run is None:
        return None
    if action_run.mode not in SHAREABLE_MODES:
        return None
    if not action_run.share_token:
        return None

    scenario = await db.scalar(select(Scenario).where(Scenario.id == action_run.scenario_id))
    if scenario is None:
        return None

    player_user = None
    if action_run.user_id:
        player_user = await db.scalar(select(User).where(User.id == action_run.user_id))

    # Daily shared seed → never include targets, even via share-token entry.
    include_targets = action_run.mode == "scenario"
    return build_ghost_dto(
        action_run,
        scenario=scenario,
        player_label=public_player_label(player_user),
        include_targets=include_targets,
        identity="share_token",
        share_token=share_token,
    )
