"""Live Arena Mode: the AI attacker policy bot (Phase D).

Deterministic, rule-based policy that plays the attacker side of a
`human_defends_vs_ai` arena match — see docs/plans/live-arena-mode.md,
"Phase D — AI attacker policy bot". This module intentionally does NOT call
`apply_attacker_action` itself: `choose_attacker_action` only DECIDES what
action to attempt next; the caller (the bot driver loop in
`app/websocket/handlers.py`) is responsible for actually applying/persisting
it through the exact same locked critical section a human's `attacker_action`
WS message goes through. That keeps this module a pure decision function,
easy to unit-test in isolation and impossible to accidentally wire into a
second, parallel persistence path.

Design notes:
- No LLM call anywhere in this module, per the plan's explicit anti-pattern
  guard — this is a fast, deterministic, explainable rule-based policy only.
- No global `random` module usage — every random choice goes through the
  `rng: random.Random` instance the caller passes in. Callers should derive
  that instance the same way `org_simulation._derive_rng` does (from the
  match seed + the action's sequence_number) so bot play is exactly as
  reproducible as a human's, which is what makes two runs with the same seed
  produce an identical move sequence (see test_arena_ai_attacker.py).
- "Known to attacker" simplification: `OrgState` (org_simulation.py) does not
  track a separate fog-of-war/attacker-knowledge view — every entity is
  either in the object graph or it isn't, and nothing marks a Host/Segment as
  "discovered". Rather than inventing a new engine capability (explicitly
  disallowed by the phase brief), this policy uses the simpler approach the
  brief calls out as acceptable: the bot always issues a handful of
  discover_segment/discover_host actions first (bounded by difficulty),
  before it ever attempts an action with real state-changing effect. This
  mirrors how a human player would plausibly open a match, costs nothing
  extra to implement, and never requires touching org_simulation.py.
- Preconditions are never re-implemented here. Every candidate action this
  module proposes is validated the same way a human's would be: the bot
  driver loop calls `apply_attacker_action` on it and trusts its graceful
  no-op-on-invalid-precondition contract. This module's OWN job is just to
  pick a plausible, high-value candidate — it pre-filters using read-only
  knowledge of the entity model (e.g. "don't bother proposing gain_foothold
  on a host that's already compromised") purely as a quality/performance
  heuristic, not as a second source of truth for precondition correctness.
"""

from __future__ import annotations

import random
from typing import Optional

from app.services.org_simulation import OrgState


# Number of discover_segment/discover_host actions the bot issues before it
# ever attempts an action with real state-changing effect, keyed by
# difficulty. Kept deliberately small (v1 scope, per the plan) — this is the
# "simplify for v1" approach the phase brief explicitly sanctions instead of
# introducing a real fog-of-war attacker-knowledge model into OrgState.
_DISCOVERY_BUDGET = {"easy": 2, "medium": 3, "hard": 4}

# How many of the (real, precondition-satisfiable) candidate actions the bot
# considers before picking one. "hard" evaluates the full action space every
# time and always takes the best-scoring candidate; "easy" only looks at a
# handful and has a real chance of picking a mediocre one; "medium" sits in
# between. This is what "harder bot evaluates more of the state graph,
# easier bot acts more greedily/noisily" (Phase D brief) means concretely.
_CANDIDATE_POOL_SIZE = {"easy": 2, "medium": 4, "hard": 999}

# Probability the bot picks a uniformly random candidate from its considered
# pool instead of the highest-scoring one — the "possibly has a chance to
# pick a bad candidate" behavior called for by the brief. Zero for "hard" so
# it is always optimal given what it considered.
_NOISE_PROBABILITY = {"easy": 0.35, "medium": 0.12, "hard": 0.0}

_VALID_DIFFICULTIES = ("easy", "medium", "hard")


def _normalize_difficulty(difficulty: str) -> str:
    return difficulty if difficulty in _VALID_DIFFICULTIES else "medium"


# ── Action scoring ───────────────────────────────────────────────────────────
#
# A candidate action's "value" is a coarse, legible heuristic reflecting how
# much it advances the attacker's position — not a learned/trained score.
# Higher is better. deploy_impact (the match-ending action) always scores
# highest once it's viable so the bot presses the win the moment it can,
# matching a rational human attacker's incentive.

_BASE_SCORES = {
    "deploy_impact": 100,
    "escalate_privilege": 40,
    "lateral_move": 35,
    "dump_credentials": 25,
    "gain_foothold": 20,
    "discover_host": 10,
    "discover_segment": 8,
}


def _candidate_discover_segment_actions(state: OrgState) -> list[dict]:
    return [
        {"action_type": "discover_segment", "payload": {"segment_id": seg.id}}
        for seg in state.segments
    ]


def _candidate_discover_host_actions(state: OrgState) -> list[dict]:
    return [
        {"action_type": "discover_host", "payload": {"host_id": h.id}}
        for h in state.hosts
        if not h.isolated
    ]


def _candidate_gain_foothold_actions(state: OrgState) -> list[dict]:
    return [
        {"action_type": "gain_foothold", "payload": {"host_id": h.id}}
        for h in state.hosts
        if not h.isolated and h.compromise_level == "none"
    ]


def _candidate_dump_credentials_actions(state: OrgState) -> list[dict]:
    """Only propose dump_credentials on a host that still has at least one
    un-harvested, non-disabled credential valid on it — otherwise the
    action is a guaranteed no-op (already harvested everything there is to
    harvest on that host) and repeatedly proposing it would stall the bot's
    progress instead of moving on to a more useful action."""
    candidates = []
    for h in state.hosts:
        if h.isolated or h.compromise_level == "none":
            continue
        has_unharvested = any(
            h.id in c.valid_on_host_ids and not c.harvested and not c.disabled
            for c in state.credentials
        )
        if has_unharvested:
            candidates.append({"action_type": "dump_credentials", "payload": {"host_id": h.id}})
    return candidates


def _candidate_escalate_privilege_actions(state: OrgState) -> list[dict]:
    return [
        {"action_type": "escalate_privilege", "payload": {"host_id": h.id}}
        for h in state.hosts
        if not h.isolated and h.compromise_level in ("foothold", "admin") and h.unpatched_cves
    ]


_COMPROMISE_ORDER = {"none": 0, "foothold": 1, "admin": 2, "domain_admin": 3}
_PRIVILEGE_TO_LEVEL = {"user": "foothold", "admin": "admin", "domain_admin": "domain_admin"}


def _candidate_lateral_move_actions(state: OrgState) -> list[dict]:
    """Only propose lateral_move where it would actually change the target
    host's compromise_level — mirrors apply_attacker_action's own
    "never downgrade an already-more-compromised host" rule (see
    org_simulation.py). Proposing a lateral_move that's a guaranteed no-op
    (e.g. re-using the same credential against a host already at or above
    the level that credential would grant) would otherwise make the bot
    loop forever restating the same no-op instead of trying something that
    actually progresses the match."""
    candidates = []
    for cred in state.credentials:
        if not cred.harvested or cred.disabled:
            continue
        granted_level = _PRIVILEGE_TO_LEVEL.get(cred.privilege, "foothold")
        for host_id in cred.valid_on_host_ids:
            target = state.get_host(host_id)
            if target is None or target.isolated:
                continue
            if _COMPROMISE_ORDER[granted_level] <= _COMPROMISE_ORDER[target.compromise_level]:
                continue  # would be a no-op: target already at/above this credential's level
            candidates.append({
                "action_type": "lateral_move",
                "payload": {"credential_id": cred.id, "target_host_id": host_id},
            })
    return candidates


def _candidate_deploy_impact_actions(state: OrgState) -> list[dict]:
    high_compromise_hosts = [h for h in state.hosts if h.compromise_level in ("admin", "domain_admin")]
    if len(high_compromise_hosts) < 2:
        return []
    return [
        {"action_type": "deploy_impact", "payload": {"host_id": h.id}}
        for h in high_compromise_hosts
        if not h.isolated
    ]


def _score(action: dict) -> int:
    return _BASE_SCORES.get(action["action_type"], 0)


def choose_attacker_action(
    state: OrgState,
    difficulty: str,
    rng: random.Random,
    actions_taken: int = 0,
) -> Optional[dict]:
    """Pick the AI attacker's next action against real `OrgState`.

    Returns an action dict shaped exactly like a human `attacker_action` WS
    message's payload: `{"action_type": str, "payload": dict}`. Returns
    `None` if no viable action exists (match should end / bot is stuck) —
    callers should treat that as a signal to stop the bot loop.

    `actions_taken` is simply the count of attacker actions this bot has
    already submitted in the match so far (i.e. `len(action_dicts)`
    restricted to actor == "attacker", or just the bot's own move counter in
    the driver loop) — used only to gate the "discover first" opening
    heuristic described in the module docstring. It defaults to 0, which is
    always a safe (if slightly more discovery-happy) fallback for a caller
    that doesn't track it, since discover_* actions are side-effect-free
    recon and never fail or waste real match state.

    Determinism: identical (state, difficulty, rng-state, actions_taken)
    always produces the identical chosen action. This function never
    touches the global `random` module — only `rng`.
    """
    difficulty = _normalize_difficulty(difficulty)

    # ── Early priority: discovery-equivalent actions first ──
    # OrgState has no attacker-knowledge/fog-of-war model to read "have I
    # discovered this host yet" from directly (see module docstring) — the
    # simplification the phase brief sanctions is to always front-load a
    # bounded number of discover_host/discover_segment actions before
    # attempting anything with real state-changing effect, using the bot's
    # own action count (not engine state) as the gate.
    discovery_budget = _DISCOVERY_BUDGET[difficulty]
    if actions_taken < discovery_budget:
        discovery_candidates = _candidate_discover_host_actions(state) or _candidate_discover_segment_actions(state)
        if discovery_candidates:
            return rng.choice(discovery_candidates)
        # No hosts/segments at all (degenerate org) — fall through to the
        # normal candidate evaluation below rather than getting stuck.

    # ── Otherwise: evaluate available actions against current state ──
    candidate_builders = (
        _candidate_deploy_impact_actions,
        _candidate_escalate_privilege_actions,
        _candidate_lateral_move_actions,
        _candidate_dump_credentials_actions,
        _candidate_gain_foothold_actions,
        _candidate_discover_host_actions,
        _candidate_discover_segment_actions,
    )
    all_candidates: list[dict] = []
    for builder in candidate_builders:
        all_candidates.extend(builder(state))

    if not all_candidates:
        return None

    # Sort by descending score for a stable, legible ordering before
    # truncating to the difficulty's considered pool size. Python's sort is
    # stable, and the candidate lists above are built in a deterministic
    # order from `state.hosts`/`state.credentials` (themselves deterministic
    # tuples), so this ordering is reproducible given the same state.
    all_candidates.sort(key=_score, reverse=True)

    pool_size = _CANDIDATE_POOL_SIZE[difficulty]
    considered = all_candidates[:pool_size] if pool_size < len(all_candidates) else all_candidates

    noise_probability = _NOISE_PROBABILITY[difficulty]
    if noise_probability > 0 and rng.random() < noise_probability:
        return rng.choice(considered)

    # Optimal-given-what-was-considered: highest score in the considered
    # pool. Ties broken deterministically via rng.choice over the tied set
    # (still deterministic given rng's state — not a "which is best" call).
    top_score = _score(considered[0])
    top_candidates = [c for c in considered if _score(c) == top_score]
    return rng.choice(top_candidates) if len(top_candidates) > 1 else top_candidates[0]
