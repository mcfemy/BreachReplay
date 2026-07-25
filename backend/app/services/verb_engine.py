"""
Phase 2 — Action console core loop: verb application layer.

BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4 / docs/PHASE2_KICKOFF.md Part B,
Item 1. Sits directly on top of action_engine.py's compiler: given a
CompiledRun and a `RunState` (this run's live, server-only progress), each of
the 8 spec verbs advances the run clock by its fixed cost, applies its
effect against the live world, and returns a narrow, client-safe delta of
only what was newly revealed. `RunState`/`CompiledRun` themselves are never
serialized to the client wholesale — see `apply_verb`'s docstring.

Server-authoritative, deterministic, frozen-dataclass style throughout,
matching action_engine.py and org_simulation.py's conventions: every
state-changing function returns a NEW `RunState` rather than mutating
anything in place.

The WebSocket wiring that calls `apply_verb` per `action.submit` message and
turns its delta into a `state.delta` broadcast is a later Phase 2 commit
(Item 3), built on top of this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from app.services.action_engine import CompiledRun, Host, IOCPlacement, OrgState

# ── Verb vocabulary ──────────────────────────────────────────────────────────
#
# Costs are BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4's table, verbatim —
# not tunable without a spec change.

VERB_COSTS: dict[str, int] = {
    "query_logs": 30,
    "scan_network": 45,
    "isolate": 20,
    "image_disk": 90,
    "interview_user": 60,
    "block_ip": 15,
    "reset_creds": 40,
    "escalate": 0,
}

# Verbs that operate against a specific target string (host id / ip / account
# username). "escalate" and "scan_network" are the two verbs with no target.
_TARGETED_VERBS = frozenset(VERB_COSTS) - {"escalate", "scan_network"}

ESCALATE_FREEZE_SECONDS = 60

# Scoring amounts are provisional pending Item 3/4's real scoring formula
# (feeding xp_service.award_xp) — tracked here only as penalty *events* with
# a numeric weight, not a final score.
ESCALATE_PENALTY = 100
PRECISION_PENALTY = 50

_COMPROMISE_LEVELS = ("none", "foothold", "admin", "domain_admin")


@dataclass(frozen=True)
class RunState:
    """The full, server-only live state of an in-progress action-mode run.
    Never sent to the client wholesale — verb handlers return only a
    narrow `VerbResult.delta` of what changed. `world` reflects both the
    attacker's stage progression AND every defender verb effect applied so
    far (isolation, credential resets, ...) folded together, the same way
    org_simulation.OrgState folds Arena actions."""

    compiled: CompiledRun
    world: OrgState
    elapsed_seconds: int = 0
    attacker_clock_offset: int = 0
    escalate_used: bool = False
    revealed_host_ids: frozenset = field(default_factory=frozenset)
    discovered_ioc_keys: frozenset = field(default_factory=frozenset)  # {(host_id, rule_id)}
    penalties: tuple = ()
    action_log: tuple = ()


@dataclass(frozen=True)
class VerbResult:
    run: RunState
    delta: dict
    error: Optional[str] = None


def new_run(compiled: CompiledRun) -> RunState:
    """A fresh RunState at t=0: no clock spent, nothing revealed. `world ==
    compiled.world`, which already has every stage through
    `compiled.breach_head_start_seconds` folded in (action_engine.py's
    "incident already in progress" fix) — identical to
    action_engine.world_state_at(compiled, 0), not a pristine, all-clean
    world.

    `attacker_clock_offset` starts NEGATIVE, at
    `-compiled.breach_head_start_seconds`, so `attacker_clock_seconds`
    below reads `breach_head_start_seconds` at elapsed_seconds=0 instead of
    0 — the attacker's effective clock starts already that far ahead,
    exactly matching what's already been folded into `world`. This is what
    makes `_advance_stages` (called from `apply_verb` below) safe to run
    completely unchanged: its (from_clock, to_clock] window never revisits
    a stage at or before `breach_head_start_seconds`, since `from_clock`
    for the very first verb is `attacker_clock_seconds(run)` at t=0, i.e.
    `breach_head_start_seconds` itself — so no stage already baked into
    `world` is ever double-applied."""
    return RunState(compiled=compiled, world=compiled.world, attacker_clock_offset=-compiled.breach_head_start_seconds)


def attacker_clock_seconds(run: RunState) -> int:
    """The attacker's own effective clock: `elapsed_seconds -
    attacker_clock_offset`. `attacker_clock_offset` starts negative (see
    new_run) so this clock starts AHEAD of `elapsed_seconds` by
    `breach_head_start_seconds` — the attacker doesn't pause and wait for
    the player to show up. `escalate` then ADDS a fixed 60s to the offset
    (a "management call" buys 60s of attacker inactivity, not a time-boxed
    pause window), which first eats into that head start and, once the
    offset turns positive, makes the clock lag `elapsed_seconds` instead."""
    return max(0, run.elapsed_seconds - run.attacker_clock_offset)


def _attack_path_host_ids(compiled: CompiledRun) -> frozenset:
    """Every host_id the attacker's stage timeline ever targets — used to
    judge whether an `isolate`/`block_ip` call actually hit a real target
    ("precision", per the spec's scoring bullet) or was wasted."""
    ids: set = set()
    for stage in compiled.stages:
        ids.update(stage.compromises_host_ids)
    return frozenset(ids)


def _set_host_isolated(world: OrgState, host_id: str) -> OrgState:
    if world.get_host(host_id) is None:
        return world
    new_hosts = tuple(
        (replace(h, isolated=True) if h.id == host_id else h) for h in world.hosts
    )
    return OrgState(
        hosts=new_hosts, segments=world.segments, credentials=world.credentials,
        detection_rules=world.detection_rules, global_flags=world.global_flags,
    )


def _host_summary(host: Host) -> dict:
    """The fog-of-war-safe view of a host once its existence is revealed
    (query_logs/scan_network/image_disk): identity + current status, but
    NOT unpatched_cves/edr_installed — those stay hidden until a deeper
    verb (image_disk) earns them."""
    return {
        "id": host.id,
        "hostname": host.hostname,
        "role": host.role,
        "network_segment_id": host.network_segment_id,
        "compromise_level": host.compromise_level,
        "isolated": host.isolated,
    }


def _revealed_edges(compiled: CompiledRun, revealed_host_ids: frozenset) -> list[dict]:
    """`compiled.edges` (topology only — source/target host ids, computed
    once at compile time, never scenario content) filtered to pairs where
    BOTH endpoints are in `revealed_host_ids`. An edge touching a host the
    player hasn't earned yet would itself leak that host's existence, so
    this is never sent unfiltered — same fog-of-war contract every other
    delta in this module already enforces."""
    return [
        e.to_dict() for e in compiled.edges
        if e.source in revealed_host_ids and e.target in revealed_host_ids
    ]


def _advance_stages(compiled: CompiledRun, world: OrgState, from_clock: int, to_clock: int) -> OrgState:
    """Apply every stage whose trigger_seconds falls in (from_clock,
    to_clock] against `world`, respecting CURRENT isolation — an isolated
    host never gets compromised further, matching org_simulation's "no
    remediation, only containment" philosophy. Mirrors
    action_engine.world_state_at's loop, but scoped to a window and folded
    onto a live `world` (which may already carry defender verb effects)
    instead of always starting fresh from compiled.world."""
    if to_clock <= from_clock:
        return world
    for stage in compiled.stages:
        if not (from_clock < stage.trigger_seconds <= to_clock):
            continue
        for host_id in stage.compromises_host_ids:
            host = world.get_host(host_id)
            if host is None or host.isolated:
                continue
            idx = _COMPROMISE_LEVELS.index(host.compromise_level)
            next_level = _COMPROMISE_LEVELS[min(idx + 1, len(_COMPROMISE_LEVELS) - 1)]
            if next_level == host.compromise_level:
                continue
            new_hosts = tuple(
                (replace(h, compromise_level=next_level) if h.id == host_id else h)
                for h in world.hosts
            )
            world = OrgState(
                hosts=new_hosts, segments=world.segments, credentials=world.credentials,
                detection_rules=world.detection_rules, global_flags=world.global_flags,
            )
    return world


def _reveal_iocs_for_host(
    compiled: CompiledRun, discovered_ioc_keys: frozenset, host_id: str,
) -> tuple[list[dict], frozenset]:
    """Every IOCPlacement bound to host_id that hasn't already been
    discovered — returns (client-safe dicts to include in the delta, the
    updated discovered_ioc_keys set). Shared by query_logs and image_disk."""
    newly: list[IOCPlacement] = [
        p for p in compiled.ioc_placements
        if p.host_id == host_id and (p.host_id, p.rule_id) not in discovered_ioc_keys
    ]
    updated_keys = discovered_ioc_keys | {(p.host_id, p.rule_id) for p in newly}
    return [p.to_dict() for p in newly], updated_keys


def _log_entry(sequence_number: int, verb: str, target: Optional[str], elapsed_seconds: int, cost: int) -> dict:
    return {
        "sequence_number": sequence_number,
        "verb": verb,
        "target": target,
        "elapsed_seconds": elapsed_seconds,
        "cost": cost,
    }


def apply_verb(run: RunState, verb: str, target: Optional[str] = None) -> VerbResult:
    """Apply one of the 8 spec verbs against `run`. Server-authoritative and
    pure: returns a NEW RunState plus a `delta` dict containing ONLY what
    this call newly revealed — never the full CompiledRun/RunState, never
    another host's unrevealed data, never a future/unfired Stage. A
    rejected call (unknown verb, missing/invalid target, escalate reused)
    returns the ORIGINAL `run` unchanged and an `error` string — validation
    failures never spend clock time."""
    if verb not in VERB_COSTS:
        return VerbResult(run=run, delta={}, error=f"Unknown verb: {verb!r}")

    if verb in _TARGETED_VERBS and not target:
        return VerbResult(run=run, delta={}, error=f"Verb {verb!r} requires a target")

    if verb == "escalate":
        if run.escalate_used:
            return VerbResult(run=run, delta={}, error="escalate already used this run")
        new_run = replace(
            run,
            escalate_used=True,
            attacker_clock_offset=run.attacker_clock_offset + ESCALATE_FREEZE_SECONDS,
            penalties=run.penalties + ({"type": "escalate_used", "amount": ESCALATE_PENALTY},),
        )
        new_run = replace(
            new_run,
            action_log=new_run.action_log + (_log_entry(
                len(new_run.action_log), "escalate", None, new_run.elapsed_seconds, 0,
            ),),
        )
        return VerbResult(run=new_run, delta={"escalate_used": True, "frozen_seconds": ESCALATE_FREEZE_SECONDS})

    world = run.world
    revealed_host_ids = run.revealed_host_ids
    discovered_ioc_keys = run.discovered_ioc_keys
    penalties = run.penalties
    delta: dict = {}

    if verb in ("query_logs", "image_disk", "interview_user", "isolate"):
        host = world.get_host(target)
        if host is None:
            return VerbResult(run=run, delta={}, error=f"Unknown host: {target!r}")

    if verb == "query_logs":
        revealed_host_ids = revealed_host_ids | {target}
        revealed_iocs, discovered_ioc_keys = _reveal_iocs_for_host(
            run.compiled, discovered_ioc_keys, target,
        )
        delta = {"host_id": target, "revealed_iocs": revealed_iocs}

    elif verb == "scan_network":
        revealed_host_ids = frozenset(h.id for h in world.hosts)
        delta = {
            "nodes": [_host_summary(h) for h in world.hosts],
            "edges": _revealed_edges(run.compiled, revealed_host_ids),
        }

    elif verb == "isolate":
        if not host.isolated:
            world = _set_host_isolated(world, target)
        on_path = target in _attack_path_host_ids(run.compiled)
        if not on_path:
            penalties = penalties + ({"type": "wrong_isolation", "host_id": target, "amount": PRECISION_PENALTY},)
        delta = {"host_id": target, "isolated": True, "on_attack_path": on_path}

    elif verb == "image_disk":
        revealed_host_ids = revealed_host_ids | {target}
        revealed_iocs, discovered_ioc_keys = _reveal_iocs_for_host(
            run.compiled, discovered_ioc_keys, target,
        )
        delta = {
            "host_id": target,
            "revealed_iocs": revealed_iocs,
            "forensics": {"unpatched_cves": list(host.unpatched_cves), "edr_installed": host.edr_installed},
        }

    elif verb == "interview_user":
        creds = [c for c in world.credentials if target in c.valid_on_host_ids]
        delta = {
            "host_id": target,
            "credentials": [{"credential_id": c.id, "username": c.username, "privilege": c.privilege} for c in creds],
        }

    elif verb == "block_ip":
        matched = next(
            (p for p in run.compiled.ioc_placements if p.matches_on.get("ip") == target),
            None,
        )
        if matched is not None:
            world = _set_host_isolated(world, matched.host_id)
            discovered_ioc_keys = discovered_ioc_keys | {(matched.host_id, matched.rule_id)}
            # matched IS added to discovered_ioc_keys above, so
            # earned_state_snapshot's revealed_iocs will include its full
            # body on any future resync regardless of what this delta
            # sends — include it here too so a live client sees the exact
            # same content immediately instead of only learning it on a
            # later reconnect. The key is genuinely earned the moment the
            # correct IP is blocked, not just recorded for scoring.
            delta = {"correct": True, "host_id": matched.host_id, "revealed_iocs": [matched.to_dict()]}
        else:
            penalties = penalties + ({"type": "wrong_block_ip", "addr": target, "amount": PRECISION_PENALTY},)
            delta = {"correct": False}

    elif verb == "reset_creds":
        # Containment verbs double as value-pivots — a deliberate convention
        # (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md), not an accident:
        # block_ip already reveals an ip-keyed hidden_ioc by value regardless
        # of which host it's bound to; this mirrors the identical pattern
        # for username-keyed ones. The two matches below are independent —
        # `target` can be a real Credential.username (containment: disables
        # it), match a hidden_ioc's matches_on.username (investigation:
        # reveals it), both, or neither. Authored scenario usernames
        # (hidden_iocs) and procedurally-generated Credential usernames
        # (org_simulation.py's own pool) are two different namespaces that
        # happen to not overlap in the 5 flagship scenarios today, so in
        # practice submitting an authored username hits only the reveal
        # path — that's fine, it's still "correct".
        cred_matched = next(
            (c for c in world.credentials if c.username == target and not c.disabled),
            None,
        )
        ioc_matched = next(
            (p for p in run.compiled.ioc_placements if p.matches_on.get("username") == target),
            None,
        )
        if cred_matched is not None:
            new_creds = tuple(
                (replace(c, disabled=True) if c.id == cred_matched.id else c) for c in world.credentials
            )
            world = OrgState(
                hosts=world.hosts, segments=world.segments, credentials=new_creds,
                detection_rules=world.detection_rules, global_flags=world.global_flags,
            )
        if ioc_matched is not None:
            discovered_ioc_keys = discovered_ioc_keys | {(ioc_matched.host_id, ioc_matched.rule_id)}

        if cred_matched is not None or ioc_matched is not None:
            delta = {"correct": True}
            if cred_matched is not None:
                delta["credential_id"] = cred_matched.id
            if ioc_matched is not None:
                # Same immediate-reveal reasoning as block_ip's own comment
                # above: earned the moment the correct username is
                # submitted, not just recorded for a later resync.
                delta["revealed_iocs"] = [ioc_matched.to_dict()]
        else:
            # Same PRECISION_PENALTY as block_ip's wrong-guess case — a
            # username guess with neither a real credential nor a hidden_ioc
            # match must cost the same as a wrong IP, or brute-forcing input
            # is cheaper than reading the alert feed and the whole
            # deduction premise collapses.
            penalties = penalties + ({"type": "wrong_reset_creds", "account": target, "amount": PRECISION_PENALTY},)
            delta = {"correct": False}

    cost = VERB_COSTS[verb]
    old_clock = attacker_clock_seconds(run)
    interim = replace(
        run,
        world=world,
        elapsed_seconds=run.elapsed_seconds + cost,
        revealed_host_ids=revealed_host_ids,
        discovered_ioc_keys=discovered_ioc_keys,
        penalties=penalties,
    )
    new_clock = attacker_clock_seconds(interim)
    advanced_world = _advance_stages(run.compiled, interim.world, old_clock, new_clock)
    final_run = replace(interim, world=advanced_world)
    final_run = replace(
        final_run,
        action_log=final_run.action_log + (_log_entry(
            len(final_run.action_log), verb, target, final_run.elapsed_seconds, cost,
        ),),
    )

    return VerbResult(run=final_run, delta=delta)


def earned_state_snapshot(run: RunState) -> dict:
    """Everything this player has earned so far, safe to resend in FULL on
    reconnect (`run.resync`) — a snapshot replay of the exact same
    fog-of-war gating `apply_verb` already enforces per-delta, not a
    relaxation of it. Without this, a reconnecting player (the whole point
    of Item 3's resume-by-run_id support) got clocks and an empty map,
    losing every host/IOC they'd already revealed — found while wiring up
    Item 5's frontend, fixed here rather than left for the UI to paper
    over. Returns `{"hosts": [...], "revealed_iocs": [...], "edges": [...]}`;
    every list is `[]` for a fresh, untouched run."""
    hosts = [h for h in run.world.hosts if h.id in run.revealed_host_ids]
    revealed_iocs = [
        p.to_dict() for p in run.compiled.ioc_placements
        if (p.host_id, p.rule_id) in run.discovered_ioc_keys
    ]
    return {
        "hosts": [_host_summary(h) for h in hosts],
        "revealed_iocs": revealed_iocs,
        "edges": _revealed_edges(run.compiled, run.revealed_host_ids),
    }


# ── Outcome + scoring (Phase 2, Item 3) ──────────────────────────────────────
#
# Pure functions over a finished/finishing RunState — no I/O, no persistence.
# The stateful layer that calls these and writes an ActionRun row is
# app.services.action_run_store.

_PARTIAL_CONTAINMENT_THRESHOLD = 0.5

# Provisional, like ESCALATE_PENALTY/PRECISION_PENALTY above — a real
# balancing pass is a later item, not this one.
SCORE_OUTCOME_BASE = {"win": 1000, "partial": 400, "loss": 0}
EVIDENCE_POINTS_PER_IOC = 100
SPEED_BONUS_PER_SECOND_SAVED = 2


def is_run_over(run: RunState, cap_seconds: Optional[int]) -> bool:
    """True once further play cannot change the outcome — the stateful
    layer (app.services.action_run_store) calls this after every applied
    verb to decide whether to auto-finalize. Two conditions, either one
    sufficient:

    1. The run's time budget is exhausted: `elapsed_seconds` (the verb-cost
       game clock, NOT real wall-clock time — see action_run_store's
       module docstring for why those are tracked separately) has reached
       `cap_seconds`.
    2. The scenario's final stage has already fired on the attacker clock.
       Every earlier stage, by construction (determine_outcome's own
       is_final selection — action_engine._build_stages picks it by MAX
       trigger_seconds), has an earlier trigger_seconds, so once the final
       stage has fired the entire timeline has necessarily already played
       out — no further verb can change win/partial/loss.

    A scenario with no final stage at all (matches determine_outcome's
    same edge case) can only end via the time budget."""
    if cap_seconds is not None and run.elapsed_seconds >= cap_seconds:
        return True
    final_stage = next((s for s in run.compiled.stages if s.is_final), None)
    if final_stage is None:
        return False
    return attacker_clock_seconds(run) >= final_stage.trigger_seconds


def determine_outcome(run: RunState) -> str:
    """"win" | "partial" | "loss", per spec section 4: "contain the attack
    path before the final-stage event (exfil/encryption) fires. Partial
    containment scores partially."

    WIN: the final (is_final) stage either hasn't fired yet on the
    attacker clock, or every host it would have compromised is isolated
    (contained before/at the moment it mattered).
    LOSS/PARTIAL: the final stage fired and compromised at least one
    un-isolated host — PARTIAL if at least half of every OTHER stage's
    target hosts were isolated (meaningful containment elsewhere), else
    LOSS. A scenario with no final stage at all (malformed/empty content)
    has nothing to lose — treated as a WIN."""
    compiled = run.compiled
    final_stage = next((s for s in compiled.stages if s.is_final), None)
    if final_stage is None:
        return "win"

    clock = attacker_clock_seconds(run)
    final_fired = clock >= final_stage.trigger_seconds
    final_contained = all(
        (host := run.world.get_host(hid)) is not None and host.isolated
        for hid in final_stage.compromises_host_ids
    ) if final_stage.compromises_host_ids else True

    if not final_fired or final_contained:
        return "win"

    other_target_ids = {
        hid for s in compiled.stages if not s.is_final for hid in s.compromises_host_ids
    }
    if not other_target_ids:
        return "loss"
    contained_count = sum(
        1 for hid in other_target_ids
        if (host := run.world.get_host(hid)) is not None and host.isolated
    )
    containment_ratio = contained_count / len(other_target_ids)
    return "partial" if containment_ratio >= _PARTIAL_CONTAINMENT_THRESHOLD else "loss"


def compute_score(run: RunState, outcome: str, cap_seconds: Optional[int]) -> dict:
    """A score_breakdown dict (JSONB-storable as-is) containing both the
    leaderboard-sortable `total_score` integer and a `score_pct` (0-100)
    used to drive xp_service.check_scenario_achievements's perfect_analyst
    check (score_pct >= 100 — only reachable on a WIN with every
    discoverable IOC found and zero penalties: a genuinely flawless run)."""
    evidence_found = len(run.discovered_ioc_keys)
    evidence_total = len(run.compiled.ioc_placements)
    evidence_points = evidence_found * EVIDENCE_POINTS_PER_IOC
    penalty_total = sum(p["amount"] for p in run.penalties)

    speed_bonus = 0
    if outcome == "win" and cap_seconds:
        speed_bonus = max(0, cap_seconds - run.elapsed_seconds) * SPEED_BONUS_PER_SECOND_SAVED

    outcome_base = SCORE_OUTCOME_BASE.get(outcome, 0)
    total_score = max(0, outcome_base + evidence_points + speed_bonus - penalty_total)

    evidence_ratio = (evidence_found / evidence_total) if evidence_total else 1.0
    if outcome == "win" and not run.penalties and evidence_ratio >= 1.0:
        score_pct = 100.0
    else:
        ceiling = 100.0 if outcome == "win" else 50.0 if outcome == "partial" else 0.0
        score_pct = max(0.0, min(100.0, round(evidence_ratio * ceiling - len(run.penalties) * 10, 2)))

    return {
        "outcome": outcome,
        "outcome_base": outcome_base,
        "evidence_points": evidence_points,
        "evidence_found": evidence_found,
        "evidence_total": evidence_total,
        "speed_bonus": speed_bonus,
        "penalty_total": penalty_total,
        "penalties": list(run.penalties),
        "total_score": total_score,
        "score_pct": score_pct,
    }
