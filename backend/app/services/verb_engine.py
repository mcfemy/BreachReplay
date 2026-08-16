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
from app.services import tool_output

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
# username / notification party id). "scan_network" is the only verb
# that's NEVER targeted; "escalate" is conditionally targeted (a party id,
# only on a scenario with an authored notification_matrix — the fallback
# for a matrix-less scenario is untargeted, matching pre-Phase-3
# behavior), so it's deliberately excluded from this blanket "requires a
# target" set too — its own branch in apply_verb validates target
# requirement itself, since that's runtime-dependent, not a static
# per-verb property this frozenset can express.
_TARGETED_VERBS = frozenset(VERB_COSTS) - {"scan_network", "escalate"}

ESCALATE_FREEZE_SECONDS = 60

# Scoring amounts are provisional pending Item 3/4's real scoring formula
# (feeding xp_service.award_xp) — tracked here only as penalty *events* with
# a numeric weight, not a final score.
PRECISION_PENALTY = 50

# The pre-Phase-3 flat escalate penalty — kept alive specifically for the
# matrix-less fallback path (apply_verb's escalate branch), which must
# match pre-Phase-3 behavior exactly, penalty included (confirmed in
# review on PR #25 against `bf2687d`, the commit immediately before this
# branch: escalate always applied this penalty). On a matrix-authored
# scenario this constant is UNUSED — that path scores warranted/
# unwarranted per party instead (UNWARRANTED_NOTIFICATION_PENALTY /
# MISSED_NOTIFICATION_PENALTY below), a deliberate, real behavior
# difference between the two paths, not an oversight.
ESCALATE_PENALTY = 100

# Phase 3 — Targeted Escalation & Notification Proportionality. Same
# per-item scale as EVIDENCE_POINTS_PER_IOC (100) below: a correctly
# warranted notification is worth as much as finding an IOC. Both penalty
# directions apply per the spec — over-notifying an unwarranted party AND
# under-notifying (never notifying) a warranted one both cost, not just one
# direction. UNWARRANTED_NOTIFICATION_PENALTY is applied immediately in
# apply_verb (known the instant the call is made, same as wrong_isolation/
# wrong_block_ip); MISSED_NOTIFICATION_PENALTY can only be computed once
# the run ends (a whole-run check — was every warranted party EVER
# notified — same reason _collateral_hosts is a finalize-time check, not a
# per-action one), so it's applied in compute_score, not here.
NOTIFICATION_POINTS_PER_WARRANTED = 100
UNWARRANTED_NOTIFICATION_PENALTY = 100
MISSED_NOTIFICATION_PENALTY = 100

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
    # Phase 3 — for a scenario WITH an authored notification_matrix,
    # replaces the old one-shot-ever `escalate_used: bool`: a 5-6-party
    # matrix means a player may legitimately need to notify several
    # parties across a run, some warranted and some not, so escalate is
    # once-PER-PARTY rather than once-EVER — this set is what enforces
    # that (each party's id can only enter it once; see apply_verb's
    # escalate branch).
    notified_party_ids: frozenset = field(default_factory=frozenset)
    # Fallback flag for any scenario with NO authored notification_matrix
    # yet (found in review on PR #25 — SolarWinds was the only scenario
    # given a matrix, and escalate was a hard-erroring dead verb, with no
    # 60s clock-freeze, on the other four). On those scenarios escalate
    # behaves exactly as it did before Phase 3, penalty included:
    # untargeted, one-shot per run, 60s freeze, ESCALATE_PENALTY. The two
    # flags are never both "live" for the same scenario —
    # `notified_party_ids` for a matrix-authored one, this bool for a
    # matrix-less one — see apply_verb's escalate branch for the exact
    # fork.
    escalate_used: bool = False
    # A second round of review on PR #25: making escalate once-per-PARTY
    # let the 60s freeze stack once per successful call — a matrix with N
    # warranted parties could
    # freeze the attacker clock N*60s at zero time cost, pushing the final
    # stage's trigger permanently out of reach. Escalate itself STAYS
    # once-per-party (repeat notifications are still scored per party,
    # per spec §10) — only the clock-freeze SIDE EFFECT is capped to one
    # application per run, matching spec §4's "one-time" framing for the
    # freeze specifically. Matrix-less scenarios don't need this flag:
    # `escalate_used` already caps the entire verb (freeze included) to
    # once per run there.
    escalate_freeze_used: bool = False
    revealed_host_ids: frozenset = field(default_factory=frozenset)
    discovered_ioc_keys: frozenset = field(default_factory=frozenset)  # {(host_id, rule_id)}
    penalties: tuple = ()
    action_log: tuple = ()
    # Technique Dossier — every stage.mitre_technique whose trigger has
    # fired (_advance_stages), regardless of whether the player contained
    # it correctly. Deliberately NOT gated on penalties/outcome: dossier
    # progress tracks exposure to a technique, not mastery of it (that's
    # mastery_service's job, over a different data source). Threaded
    # through to action_run_store.finalize() for persistence.
    encountered_technique_ids: frozenset = field(default_factory=frozenset)


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


# ── Proportionate Response: collateral + grace ───────────────────────────────
#
# A host the player isolated that the attacker never touched at all — real
# incident-response collateral (Colonial's own precautionary pipeline
# shutdown is the concrete example this whole mechanic is modeled on), not
# the same thing as "isolated a host slightly off the critical path". Every
# procedurally-generated host (seed-random per playthrough — scenario mode
# uses secrets.randbelow) intentionally has no authored citation behind it;
# DEFAULT_COLLATERAL_WEIGHT is the flat, low, uncited severity it falls back
# to. See Scenario.collateral_weights' docstring and docs/BACKLOG.md's
# "final-stage target is unbound from real content" entry for why this is
# keyed by hostname rather than host_id.
DEFAULT_COLLATERAL_WEIGHT = 10


def _collateral_hosts(run: "RunState") -> list[tuple[str, str, int]]:
    """(host_id, hostname, weight) for every host the player isolated that
    the attacker's stage timeline never once targets — the collateral set.
    Weight comes from the scenario's authored `collateral_weights` dict
    (keyed by hostname), falling back to DEFAULT_COLLATERAL_WEIGHT for
    every host not in it (i.e. every procedural/padding host, whichever
    seed happened to generate it)."""
    compiled = run.compiled
    on_path = _attack_path_host_ids(compiled)
    weights = compiled.collateral_weights
    return [
        (h.id, h.hostname, weights.get(h.hostname, DEFAULT_COLLATERAL_WEIGHT))
        for h in run.world.hosts
        if h.isolated and h.id not in on_path
    ]


# Hybrid grace formula (Proportionate Response Part A — stress-tested
# against all 5 flagship scenarios' real decoy-pool sizes, not just the
# 5-host paths the spec named, before locking these two constants):
#
#   - Absolute grace floor: the first wrong isolation is always free,
#     regardless of ratio. Without this, Colonial Pipeline and SolarWinds
#     (whose decoy pools are just 2 hosts each — almost their entire map is
#     legitimately on the real attack path) would treat a single honest
#     mistake as a 50% coverage ratio, the same severity as isolating half
#     the map in a scenario like NHS. This "short ladder" — Colonial/
#     SolarWinds effectively having only ONE grace step before the ratio
#     check takes over — is intentional, not a bug: it's a direct
#     consequence of those two scenarios having almost no decoy pool to be
#     forgiving about, not an authoring inconsistency.
#   - Egregious ceiling: coverage ratio (decoys isolated / decoys
#     available) is the only one of the two candidate formulas that reads
#     100% for "isolate every revealed host" in EVERY scenario regardless
#     of decoy-pool size (a "precision" formula tuned to catch MGM/Log4Shell/
#     NHS would let Colonial/SolarWinds' isolate-everything run through as
#     merely CONTAINED AT COST — exactly the exploit this whole spec exists
#     to close).
GRACE_FLOOR_WRONG_ISOLATIONS = 1
OVERREACTED_COVERAGE_THRESHOLD = 0.6


def _grace_check(run: "RunState") -> tuple[bool, float]:
    """(within_grace, coverage_ratio). `within_grace` is True whenever the
    number of collateral (wrongly isolated) hosts is at or below the
    absolute grace floor, independent of the ratio. `coverage_ratio` is
    collateral hosts isolated / decoys actually available in this
    scenario — 0.0 (not 1.0) when there are no decoys at all, since there
    is nothing to have covered."""
    collateral = _collateral_hosts(run)
    wrong_isolated = len(collateral)
    decoy_pool = len(run.world.hosts) - len(_attack_path_host_ids(run.compiled))
    coverage_ratio = (wrong_isolated / decoy_pool) if decoy_pool else 0.0
    within_grace = wrong_isolated <= GRACE_FLOOR_WRONG_ISOLATIONS
    return within_grace, coverage_ratio


# ── Phase 3: notification proportionality ────────────────────────────────────

def _notification_summary(run: "RunState") -> tuple[list[dict], int, int]:
    """(notifications, notification_points, notification_penalty) — scored
    the same way _collateral_hosts/_grace_check score collateral: a
    whole-run check against the scenario's authored `notification_matrix`,
    not a per-action one, because "was every warranted party EVER
    notified" can only be answered once the run ends (the same reason
    collateral is a finalize-time check).

    This function only ever scores the UNDER-notification direction
    (a warranted party that never got notified) plus the reward for
    getting a warranted notification right. The OVER-notification
    direction (notifying an unwarranted party) is scored differently, on
    purpose: it's knowable the instant the call is made, so it's applied
    immediately in apply_verb's escalate branch as a normal `penalties`
    entry — same pattern as wrong_isolation/wrong_block_ip — and already
    flows into `penalty_total` below. Folding it into this function's
    `notification_penalty` too would double-count it."""
    notifications = []
    notification_points = 0
    notification_penalty = 0
    for party in run.compiled.notification_matrix:
        notified = party["id"] in run.notified_party_ids
        warranted = bool(party["warranted"])
        notifications.append({
            "party_id": party["id"], "party_name": party["party_name"],
            "warranted": warranted, "notified": notified,
        })
        if warranted and notified:
            notification_points += NOTIFICATION_POINTS_PER_WARRANTED
        elif warranted and not notified:
            notification_penalty += MISSED_NOTIFICATION_PENALTY
    return notifications, notification_points, notification_penalty


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


def _advance_stages(
    compiled: CompiledRun, world: OrgState, from_clock: int, to_clock: int,
) -> tuple[OrgState, frozenset]:
    """Apply every stage whose trigger_seconds falls in (from_clock,
    to_clock] against `world`, respecting CURRENT isolation — an isolated
    host never gets compromised further, matching org_simulation's "no
    remediation, only containment" philosophy. Mirrors
    action_engine.world_state_at's loop, but scoped to a window and folded
    onto a live `world` (which may already carry defender verb effects)
    instead of always starting fresh from compiled.world.

    Returns `(world, newly_fired_technique_ids)` — the second element is
    every `stage.mitre_technique` (deduped, None dropped) belonging to a
    stage that fired in this window, REGARDLESS of `compromises_host_ids`
    or isolation outcome: a stage "firing" is what the Technique Dossier
    means by "encountered", independent of whether it actually advanced
    any host's compromise_level."""
    newly_fired_technique_ids: set = set()
    if to_clock <= from_clock:
        return world, frozenset()
    for stage in compiled.stages:
        if not (from_clock < stage.trigger_seconds <= to_clock):
            continue
        if stage.mitre_technique:
            newly_fired_technique_ids.add(stage.mitre_technique)
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
    return world, frozenset(newly_fired_technique_ids)


def _reveal_iocs_for_host(
    compiled: CompiledRun, discovered_ioc_keys: frozenset, host_id: str,
) -> tuple[list[IOCPlacement], list[dict], frozenset]:
    """Every IOCPlacement bound to host_id that hasn't already been
    discovered — returns (the raw placements, client-safe dicts to include
    in the delta, the updated discovered_ioc_keys set). Shared by
    query_logs and image_disk. The raw placements are ALSO what
    tool_output.render_query_logs/render_image_disk take — the exact same
    already-filtered set the delta itself sends, not a re-derivation."""
    newly: list[IOCPlacement] = [
        p for p in compiled.ioc_placements
        if p.host_id == host_id and (p.host_id, p.rule_id) not in discovered_ioc_keys
    ]
    updated_keys = discovered_ioc_keys | {(p.host_id, p.rule_id) for p in newly}
    return newly, [p.to_dict() for p in newly], updated_keys


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
        if not run.compiled.notification_matrix:
            # Fallback (found in review on PR #25) — no notification_matrix
            # authored for this scenario yet. Rather than a hard-erroring
            # dead verb with no clock-freeze, behaves exactly as escalate
            # did before Phase 3, penalty included: untargeted (`target` is
            # ignored even if a caller passes one), one-shot per run, 60s
            # freeze, ESCALATE_PENALTY.
            if run.escalate_used:
                return VerbResult(run=run, delta={}, error="escalate already used this run")
            sequence_number = len(run.action_log)
            new_run = replace(
                run,
                escalate_used=True,
                attacker_clock_offset=run.attacker_clock_offset + ESCALATE_FREEZE_SECONDS,
                penalties=run.penalties + ({"type": "escalate_used", "amount": ESCALATE_PENALTY},),
            )
            new_run = replace(
                new_run,
                action_log=new_run.action_log + (_log_entry(
                    sequence_number, "escalate", None, new_run.elapsed_seconds, 0,
                ),),
            )
            escalate_output = tool_output.render_escalate(run.compiled.seed, sequence_number, None)
            return VerbResult(run=new_run, delta={
                "escalate_used": True, "frozen_seconds": ESCALATE_FREEZE_SECONDS, "tool_output": escalate_output,
            })

        if not target:
            return VerbResult(run=run, delta={}, error="Verb 'escalate' requires a target")
        party = next((p for p in run.compiled.notification_matrix if p["id"] == target), None)
        if party is None:
            return VerbResult(run=run, delta={}, error=f"Unknown notification party: {target!r}")
        if target in run.notified_party_ids:
            return VerbResult(run=run, delta={}, error=f"Party {target!r} already notified this run")

        warranted = bool(party["warranted"])
        sequence_number = len(run.action_log)
        new_penalties = run.penalties
        if not warranted:
            # Over-notification — known immediately, unlike the missed-
            # warranted-party check below, which can only be evaluated once
            # the run ends (compute_score).
            new_penalties = new_penalties + (
                {"type": "unwarranted_notification", "party_id": target, "amount": UNWARRANTED_NOTIFICATION_PENALTY},
            )
        # The 60s freeze is a one-time-per-RUN bonus (spec §4's "one-time"
        # framing), capped independent of how many parties get notified —
        # escalate itself stays once-per-PARTY for cost/scoring purposes
        # (repeat notifications are still individually scored per §10),
        # only this side effect is capped. Second-round review finding on
        # PR #25: without this cap, a matrix with N warranted parties let
        # a player freeze the attacker clock N*60s at zero time cost,
        # pushing the final stage's trigger permanently out of reach.
        freeze_seconds_applied = 0 if run.escalate_freeze_used else ESCALATE_FREEZE_SECONDS
        new_run = replace(
            run,
            notified_party_ids=run.notified_party_ids | {target},
            attacker_clock_offset=run.attacker_clock_offset + freeze_seconds_applied,
            escalate_freeze_used=True,
            penalties=new_penalties,
        )
        new_run = replace(
            new_run,
            # `warranted` rides alongside the standard log-entry shape (same
            # pattern block_ip/reset_creds use for their own extra
            # `correct` flag) — this is what lets cmmc_evidence.py's
            # aggregate finally answer "which declared obligation, if any,
            # did this escalation satisfy" instead of just "an escalation
            # occurred" (see that module's docstring, the exact gap this
            # closes).
            action_log=new_run.action_log + ({
                **_log_entry(sequence_number, "escalate", target, new_run.elapsed_seconds, 0),
                "warranted": warranted,
            },),
        )
        escalate_output = tool_output.render_escalate(run.compiled.seed, sequence_number, party["party_name"])
        return VerbResult(run=new_run, delta={
            "party_id": target, "party_name": party["party_name"], "warranted": warranted,
            # Reflects what THIS call actually did — 0 on every notification
            # after the run's first (the freeze cap above), not a claim
            # that this call froze the clock when it didn't.
            "frozen_seconds": freeze_seconds_applied, "tool_output": escalate_output,
        })

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
        revealed_placements, revealed_iocs, discovered_ioc_keys = _reveal_iocs_for_host(
            run.compiled, discovered_ioc_keys, target,
        )
        delta = {
            "host_id": target,
            "revealed_iocs": revealed_iocs,
            "tool_output": tool_output.render_query_logs(run.compiled.seed, host, revealed_placements, run.elapsed_seconds),
        }

    elif verb == "scan_network":
        revealed_host_ids = frozenset(h.id for h in world.hosts)
        delta = {
            "nodes": [_host_summary(h) for h in world.hosts],
            "edges": _revealed_edges(run.compiled, revealed_host_ids),
            "tool_output": tool_output.render_scan_network(run.compiled.seed, list(world.hosts), run.elapsed_seconds),
        }

    elif verb == "isolate":
        if not host.isolated:
            world = _set_host_isolated(world, target)
        on_path = target in _attack_path_host_ids(run.compiled)
        if not on_path:
            penalties = penalties + ({"type": "wrong_isolation", "host_id": target, "amount": PRECISION_PENALTY},)
        delta = {
            "host_id": target, "isolated": True, "on_attack_path": on_path,
            "tool_output": tool_output.render_isolate(host),
        }

    elif verb == "image_disk":
        revealed_host_ids = revealed_host_ids | {target}
        revealed_placements, revealed_iocs, discovered_ioc_keys = _reveal_iocs_for_host(
            run.compiled, discovered_ioc_keys, target,
        )
        delta = {
            "host_id": target,
            "revealed_iocs": revealed_iocs,
            "forensics": {"unpatched_cves": list(host.unpatched_cves), "edr_installed": host.edr_installed},
            "tool_output": tool_output.render_image_disk(
                run.compiled.seed, host, revealed_placements,
                list(host.unpatched_cves), host.edr_installed, run.elapsed_seconds,
            ),
        }

    elif verb == "interview_user":
        creds = [c for c in world.credentials if target in c.valid_on_host_ids]
        cred_dicts = [{"credential_id": c.id, "username": c.username, "privilege": c.privilege} for c in creds]
        delta = {
            "host_id": target,
            "credentials": cred_dicts,
            "tool_output": tool_output.render_interview_user(host, cred_dicts),
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
            delta = {
                "correct": True, "host_id": matched.host_id, "revealed_iocs": [matched.to_dict()],
                "tool_output": tool_output.render_block_ip(target),
            }
        else:
            penalties = penalties + ({"type": "wrong_block_ip", "addr": target, "amount": PRECISION_PENALTY},)
            delta = {"correct": False, "tool_output": tool_output.render_block_ip(target)}

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

        matched = cred_matched is not None or ioc_matched is not None
        if matched:
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
        delta["tool_output"] = tool_output.render_reset_creds(target, matched)

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
    advanced_world, newly_fired_technique_ids = _advance_stages(run.compiled, interim.world, old_clock, new_clock)
    final_run = replace(
        interim,
        world=advanced_world,
        encountered_technique_ids=interim.encountered_technique_ids | newly_fired_technique_ids,
    )
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
        # Phase 3 — same reconnect-gap discipline Item 3 already applied to
        # hosts/revealed_iocs/edges above: without this, a reconnecting
        # player's client-side "already notified" tracking would silently
        # reset to empty even though the server still enforces once-per-
        # party server-side, so a reconnect could tap an already-notified
        # party and learn only from a rejection error instead of the
        # picker correctly greying it out. Not leak-safety-sensitive like
        # the others (a party id a player already notified isn't a spoiler
        # — they picked it themselves).
        "notified_party_ids": sorted(run.notified_party_ids),
    }


def public_notification_parties(compiled: CompiledRun) -> list[dict]:
    """The `{id, party_name}` pairs a player picks from when tapping
    "Escalate" — deliberately excludes `warranted`/`basis`/`rationale`/
    `source_reference`: those ARE the answer to the judgment call this
    verb exists to test, so sending them up front would hand the player
    the puzzle's solution the same way leaking an unrevealed IOC would.
    Known from run start (this is a static per-scenario list, not
    progressively earned like hosts/IOCs), so it's sent once in
    run.resync, never gated behind fog-of-war."""
    return [{"id": p["id"], "party_name": p["party_name"]} for p in compiled.notification_matrix]


# ── Outcome + scoring (Phase 2, Item 3) ──────────────────────────────────────
#
# Pure functions over a finished/finishing RunState — no I/O, no persistence.
# The stateful layer that calls these and writes an ActionRun row is
# app.services.action_run_store.

_PARTIAL_CONTAINMENT_THRESHOLD = 0.5

# Provisional, like UNWARRANTED_NOTIFICATION_PENALTY/PRECISION_PENALTY
# above — a real balancing pass is a later item, not this one.
#
# `overreacted` (200) deliberately scores BELOW `breached_spread_limited`
# (400), even though `overreacted` means the final target WAS stopped and
# `breached_spread_limited` means it wasn't. This is not an ordering
# accident — it's the point of the whole spec: stopping the final target is
# necessary but not sufficient for a good score. A responder who isolates
# most of the network to be safe hasn't demonstrated more skill than one
# who reasoned carefully and contained most of the spread with targeted
# action. Colonial Pipeline's real 2021 precautionary shutdown is the
# concrete example this mirrors — the decision to shut the pipeline down
# cost more than the ransomware's actual, unconfirmed OT impact would have.
# Proportionality is scored independently of raw success.
SCORE_OUTCOME_BASE = {
    "contained": 1000,
    "contained_at_cost": 600,
    "overreacted": 200,
    "breached_spread_limited": 400,
    "breached": 0,
}
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
    """"contained" | "contained_at_cost" | "overreacted" |
    "breached_spread_limited" | "breached" — Proportionate Response's
    5-state outcome, graded on two independent axes: was the final target
    stopped, and how much collateral (hosts isolated that the attacker
    never touched — see `_collateral_hosts`) did it cost.

    Axis 1 — was the final target stopped: the final (is_final) stage
    either hasn't fired yet on the attacker clock, or every host it would
    have compromised is isolated (contained before/at the moment it
    mattered). A scenario with no final stage at all (malformed/empty
    content) has nothing to lose — treated as contained.

    If the final target was NOT stopped, collateral is moot — the outcome
    is graded exactly like the old win/partial/loss split (renamed, same
    _PARTIAL_CONTAINMENT_THRESHOLD, same "preserve today's partial-credit
    concept" requirement): `breached_spread_limited` if at least half of
    every OTHER stage's target hosts were isolated, else `breached`.

    If the final target WAS stopped, axis 2 (collateral, via
    `_grace_check`'s hybrid grace-floor + coverage-ratio formula — see that
    function's docstring for the full rationale) decides between the three
    "final target stopped" states: `contained` (within the grace floor),
    `contained_at_cost` (some avoidable collateral but under the egregious
    threshold), or `overreacted` (coverage ratio over
    OVERREACTED_COVERAGE_THRESHOLD — isolated most of the map to be safe)."""
    compiled = run.compiled
    final_stage = next((s for s in compiled.stages if s.is_final), None)
    if final_stage is None:
        return "contained"

    clock = attacker_clock_seconds(run)
    final_fired = clock >= final_stage.trigger_seconds
    final_contained = all(
        (host := run.world.get_host(hid)) is not None and host.isolated
        for hid in final_stage.compromises_host_ids
    ) if final_stage.compromises_host_ids else True

    if not final_fired or final_contained:
        within_grace, coverage_ratio = _grace_check(run)
        if within_grace:
            return "contained"
        if coverage_ratio > OVERREACTED_COVERAGE_THRESHOLD:
            return "overreacted"
        return "contained_at_cost"

    other_target_ids = {
        hid for s in compiled.stages if not s.is_final for hid in s.compromises_host_ids
    }
    if not other_target_ids:
        return "breached"
    contained_count = sum(
        1 for hid in other_target_ids
        if (host := run.world.get_host(hid)) is not None and host.isolated
    )
    containment_ratio = contained_count / len(other_target_ids)
    return "breached_spread_limited" if containment_ratio >= _PARTIAL_CONTAINMENT_THRESHOLD else "breached"


def compute_score(run: RunState, outcome: str, cap_seconds: Optional[int]) -> dict:
    """A score_breakdown dict (JSONB-storable as-is) containing both the
    leaderboard-sortable `total_score` integer and a `score_pct` (0-100)
    used to drive xp_service.check_scenario_achievements's perfect_analyst
    check (score_pct >= 100 — only reachable on a `contained` run with
    every discoverable IOC found, zero penalties, and zero collateral: a
    genuinely flawless run).

    `collateral` is the post-run debrief's collateral breakdown (see
    `_collateral_hosts`) — leak-safe by construction: this dict is only
    ever built once, at run.end (action_run_store.finalize), and only ever
    reaches the client via that single post-run summary event, never a
    mid-run delta. `collateral_penalty` (the sum of those hosts' weights)
    is deducted from score the same way `penalty_total` already is."""
    evidence_found = len(run.discovered_ioc_keys)
    evidence_total = len(run.compiled.ioc_placements)
    evidence_points = evidence_found * EVIDENCE_POINTS_PER_IOC
    penalty_total = sum(p["amount"] for p in run.penalties)

    collateral = _collateral_hosts(run)
    collateral_penalty = sum(weight for _hid, _hostname, weight in collateral)

    # Phase 3 — notification proportionality: parallel to evidence_points,
    # additive into total_score, never touching `outcome` (determine_outcome
    # never reads notification data) or score_pct's ceiling below — a
    # separate axis, not a second UI-surfaced score.
    notifications, notification_points, notification_penalty = _notification_summary(run)

    speed_bonus = 0
    if outcome == "contained" and cap_seconds:
        speed_bonus = max(0, cap_seconds - run.elapsed_seconds) * SPEED_BONUS_PER_SECOND_SAVED

    outcome_base = SCORE_OUTCOME_BASE.get(outcome, 0)
    total_score = max(0, (
        outcome_base + evidence_points + speed_bonus + notification_points
        - penalty_total - collateral_penalty - notification_penalty
    ))

    evidence_ratio = (evidence_found / evidence_total) if evidence_total else 1.0
    if outcome == "contained" and not run.penalties and not collateral and evidence_ratio >= 1.0:
        score_pct = 100.0
    else:
        ceiling = {
            "contained": 100.0, "contained_at_cost": 75.0, "overreacted": 25.0,
            "breached_spread_limited": 50.0, "breached": 0.0,
        }.get(outcome, 0.0)
        deduction = len(run.penalties) * 10 + len(collateral) * 5
        score_pct = max(0.0, min(100.0, round(evidence_ratio * ceiling - deduction, 2)))

    return {
        "outcome": outcome,
        "outcome_base": outcome_base,
        "evidence_points": evidence_points,
        "evidence_found": evidence_found,
        "evidence_total": evidence_total,
        "speed_bonus": speed_bonus,
        "penalty_total": penalty_total,
        "penalties": list(run.penalties),
        "collateral": [
            {"host_id": hid, "hostname": hostname, "weight": weight}
            for hid, hostname, weight in collateral
        ],
        "collateral_penalty": collateral_penalty,
        "notifications": notifications,
        "notification_points": notification_points,
        "notification_penalty": notification_penalty,
        "total_score": total_score,
        "score_pct": score_pct,
    }
