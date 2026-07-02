"""Live Arena Mode: the AI defender policy bot (Phase E).

Deterministic, rule-based policy that plays the defender side of a
`human_attacks_vs_ai` arena match — see docs/plans/live-arena-mode.md,
"Phase E — AI defender policy bot". This module intentionally does NOT call
`apply_defender_action` itself: `choose_defender_action` only DECIDES what
response to attempt next; the caller (the reactive trigger in
`app/websocket/handlers.py`) is responsible for actually applying/persisting
it through the exact same locked critical section a human's `defender_action`
WS message goes through. Mirrors `arena_ai_attacker.py`'s separation of
concerns exactly, for the same reason: keeps this module a pure decision
function, easy to unit-test in isolation and impossible to accidentally wire
into a second, parallel persistence path.

Design notes:
- No LLM call anywhere in this module, per the plan's explicit anti-pattern
  guard — this is a fast, deterministic, explainable rule-based policy only.
- No global `random` module usage — every random choice goes through the
  `rng: random.Random` instance the caller passes in, exactly like
  `arena_ai_attacker.choose_attacker_action`.
- Reactive, not proactive: unlike the Phase D attacker bot (which always has
  a "next move" to consider and polls on a fixed interval), a defender only
  has something to react to when an attacker action just crossed a
  decision-gate-worthy threshold. This module therefore takes the SAME
  trigger context `handlers._decision_gate_trigger` already computes
  (reason/host/credential) as its input, rather than scanning the whole
  `OrgState` for "is there anything to do right now" on its own — there's
  no need to reinvent gate detection, `_decision_gate_trigger` already is
  that logic and stays the single source of truth for "does this action
  warrant a response" for BOTH the human-defender WS-event path and this
  bot's reactive path.
- Preconditions are never re-implemented here. Every candidate response this
  module proposes is validated the same way a human's would be: the caller
  applies it via `apply_defender_action` and trusts its graceful
  no-op-on-invalid-precondition contract. This module's OWN job is just to
  pick a plausible response given the trigger context — it doesn't need to
  pre-filter against the object graph the way the attacker bot does, because
  the trigger context already hands over a real, currently-valid host/
  credential id (the decision gate that produced it wouldn't have offered a
  response option otherwise).
"""

from __future__ import annotations

import random
from typing import Optional

from app.services.org_simulation import OrgState


# ── Difficulty tuning ────────────────────────────────────────────────────────
#
# Mirrors arena_ai_attacker.py's exact mechanism (candidate pool size +
# noise probability) rather than inventing a new scheme, per the phase
# brief's explicit instruction to keep difficulty tuning consistent across
# both bots.
#
# The "candidate pool" here is the ranked list of realistic responses to a
# given trigger (see `_rank_responses`), best-first. Same mechanism as
# arena_ai_attacker.py (candidate pool size + noise probability), but the
# pool-size direction is deliberately INVERTED relative to the attacker bot:
# arena_ai_attacker's candidates are all "good" moves (every candidate
# advances the attacker), so a NARROW pool of top-scored candidates plus
# noise still picks among strong options for "hard". Here, `_rank_responses`
# ranks from objectively-strong (isolate_host) down to deliberately weak
# (acknowledge) — a narrow pool anchored on the single best response would
# leave noise nothing weak to ever land on, defeating "easy sometimes picks
# a weaker response". So: "hard" considers only the top-ranked response
# (pool size 1) and, with zero noise, always takes it — reliably picking the
# objectively strong response with no chance of drifting to something worse.
# "easy" considers the FULL ranked list (including acknowledge) and has a
# real chance of noise-picking all the way down to the weak end; "medium"
# considers a middle slice. This still expresses "harder bot evaluates more
# of the option space, easier bot acts more greedily/noisily" — "evaluates
# more" here means "hard commits confidently to the one response it knows is
# right" while "easy keeps a wider, noisier set of options in play" (which
# for a defender's weaker-response risk is the analogous failure mode to the
# attacker bot's "picks a mediocre candidate").
_CANDIDATE_POOL_SIZE = {"easy": 999, "medium": 3, "hard": 1}

# Probability the bot picks a uniformly random candidate from its considered
# pool instead of the top-ranked one. Zero for "hard" so it is always optimal
# given what it considered — identical mechanism to
# arena_ai_attacker._NOISE_PROBABILITY.
_NOISE_PROBABILITY = {"easy": 0.35, "medium": 0.12, "hard": 0.0}

# Reaction delay (seconds) before the response is submitted, keyed by
# difficulty — "hard" reacts fastest/most decisively, "easy" is slower to
# respond, matching a real analyst's speed-accuracy tradeoff. Consumed by the
# caller in handlers.py (this module has no asyncio/sleep of its own — pure
# decision function only, exactly like choose_attacker_action).
REACTION_DELAY_SECONDS = {"easy": 6.0, "medium": 4.0, "hard": 2.0}

_VALID_DIFFICULTIES = ("easy", "medium", "hard")


def _normalize_difficulty(difficulty: str) -> str:
    return difficulty if difficulty in _VALID_DIFFICULTIES else "medium"


# ── Response candidate ranking ──────────────────────────────────────────────
#
# A candidate response's "value" is a coarse, legible heuristic reflecting
# how effectively it contains the situation described by the trigger — not a
# learned/trained score, mirroring arena_ai_attacker._BASE_SCORES' philosophy.
# isolate_host ranks highest when a host is offered because physically
# cutting off a host that just reached admin/domain_admin compromise (or is
# mid-impact) is the objectively strong response a real defender would reach
# for; disable_credential is the next-best targeted response;
# increase_monitoring is a real but weaker action (visibility, not
# containment); acknowledge is the weakest ("wait and watch") response and is
# always available as a fallback.

_RESPONSE_SCORES = {
    "isolate_host": 100,
    "disable_credential": 70,
    "increase_monitoring": 40,
    "acknowledge": 10,
}


def _rank_responses(host: Optional[dict], credential_id: Optional[str]) -> list[dict]:
    """Build the ranked (best-first) list of realistic response candidates
    for this trigger context, exactly mirroring the option-availability rule
    `handlers._build_arena_decision_gate` already uses: a response is only a
    candidate when every id it needs is actually available from the trigger
    context, so this bot is never proposing a response that would silently
    no-op against `apply_defender_action`'s real preconditions."""
    candidates: list[dict] = []

    if host and host.get("id"):
        candidates.append({"action_type": "isolate_host", "payload": {"host_id": host["id"]}})

    if credential_id:
        candidates.append({"action_type": "disable_credential", "payload": {"credential_id": credential_id}})

    if host and host.get("network_segment_id"):
        candidates.append({
            "action_type": "increase_monitoring",
            "payload": {"segment_id": host["network_segment_id"]},
        })

    # Always available — the "monitor and gather more evidence" fallback,
    # matching _ARENA_RESPONSE_OPTIONS' always-offered acknowledge entry.
    candidates.append({"action_type": "acknowledge", "payload": {}})

    candidates.sort(key=lambda c: _RESPONSE_SCORES.get(c["action_type"], 0), reverse=True)
    return candidates


def choose_defender_action(
    state: OrgState,
    trigger_reason: str,
    host: Optional[dict],
    credential_id: Optional[str],
    difficulty: str,
    rng: random.Random,
) -> Optional[dict]:
    """Pick the AI defender's response to a decision-gate-worthy trigger.

    `state`, `trigger_reason`, `host`, `credential_id` are exactly the
    context `handlers._decision_gate_trigger` computes for a human defender's
    decision gate (`host`/`credential_id` shaped the same way:
    `host` is a plain dict from `Host.to_dict()` or `None`,
    `credential_id` is a str or `None`). `state` is accepted for parity with
    `choose_attacker_action`'s signature shape and to leave room for a future
    difficulty tier that reasons about the wider org graph, but the v1 policy
    only needs the trigger context itself (see module docstring) — every
    realistic response is already fully determined by
    `host`/`credential_id`.

    Returns an action dict shaped exactly like a human `defender_action` WS
    message's payload: `{"action_type": str, "payload": dict}`. Never returns
    `None` in practice — `acknowledge` is always a valid fallback candidate —
    but the Optional return type is kept for symmetry with
    `choose_attacker_action` and as a defensive contract for a future
    difficulty tier that might legitimately have nothing to propose.

    Determinism: identical (trigger context, difficulty, rng-state) always
    produces the identical chosen response. This function never touches the
    global `random` module — only `rng`.
    """
    difficulty = _normalize_difficulty(difficulty)

    ranked = _rank_responses(host, credential_id)
    if not ranked:
        return None  # defensive; _rank_responses always includes acknowledge

    pool_size = _CANDIDATE_POOL_SIZE[difficulty]
    considered = ranked[:pool_size] if pool_size < len(ranked) else ranked

    noise_probability = _NOISE_PROBABILITY[difficulty]
    if noise_probability > 0 and rng.random() < noise_probability:
        return rng.choice(considered)

    # Optimal-given-what-was-considered: highest-ranked candidate in the
    # considered pool. Ties broken deterministically via rng.choice over the
    # tied set (still deterministic given rng's state — not a "which is
    # best" call), mirroring choose_attacker_action's tie-break approach.
    top_score = _RESPONSE_SCORES.get(considered[0]["action_type"], 0)
    top_candidates = [c for c in considered if _RESPONSE_SCORES.get(c["action_type"], 0) == top_score]
    return rng.choice(top_candidates) if len(top_candidates) > 1 else top_candidates[0]
