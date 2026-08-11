"""
Phase 2 — Action console core loop: the deterministic compiler.

BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4 / docs/PHASE2_KICKOFF.md Part B.

Given a Scenario's authored content (`alert_sequence`, `decision_tree`,
`pressure_injections`, `hidden_iocs`) and a seed, `compile_scenario` produces
a `CompiledRun`: a hidden, server-only world state plus a deterministic stage
timeline representing the attacker's real, unopposed progression through the
breach. Same (scenario, seed) always produces a byte-identical `CompiledRun`
— this is what Phase 4's ghost racing depends on ("same seed, same run").

World synthesis reuses `org_simulation.py`'s Arena seeded-org generator
(`generate_org_state`) rather than inventing a second host/topology model:
authored scenarios like Colonial Pipeline carry no explicit host/segment
topology of their own, only free-text hostnames inside the narrative
(`alert_sequence`/`decision_tree` prose), so there is nothing else to reuse
from, and Phase 4 already needs ghosts and live scenario runs to share the
exact same seeded-world primitives arena matches use.

Scope note: this module is the compiler only. Verb application (query logs /
isolate / etc — the player's side of the loop) and the WebSocket wiring that
submits verbs against a `CompiledRun` are a separate, later Phase 2 commit
that builds on top of this one, alongside the `action.submit`/`state.delta`
message types.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field, replace
from typing import Optional, Union

from app.services import host_harvest
from app.services.org_simulation import (
    DECISION_GATE_ARCHETYPES,
    ORG_ARCHETYPES,
    Host,
    OrgState,
    _SEGMENT_NAME_POOLS,
    generate_org_state,
)

# compile_scenario's own archetype lookup, separate from the ORG_ARCHETYPES
# dict Arena mode's matchmaking/API/tests enumerate directly — see
# org_simulation.py's DECISION_GATE_ARCHETYPES docstring for why the two
# must never merge into one shared dict.
_COMPILE_SCENARIO_ARCHETYPES: dict[str, dict] = {**ORG_ARCHETYPES, **DECISION_GATE_ARCHETYPES}

ScenarioLike = Union[dict, object]  # ORM Scenario instance, or a plain dict with the same field names

_TIMESTAMP_RE = re.compile(r'^\+(\d+)([ms])$')

# compromise_level progression order — mirrors org_simulation._COMPROMISE_ORDER,
# duplicated locally since that name is private to org_simulation.py.
_COMPROMISE_LEVELS = ("none", "foothold", "admin", "domain_admin")

# The "incident already in progress" fix: a responder walking into a real
# breach never finds a pristine network — they find a SOC that's already
# noticed *something*. Without this, world_state_at(compiled, 0) (and
# therefore the player's very first scan_network) showed every host
# "none", because compile_scenario built `world` from generate_org_state's
# pristine baseline and left stage-firing entirely to the live game clock.
#
# Fixed (already-compressed) attacker-clock seconds treated as already
# elapsed at compile time: every stage whose (post-compression_ratio)
# trigger_seconds falls at or before this gets folded into `CompiledRun.
# world` directly, not just the FIRST stage — see compile_scenario's
# `_apply_stages_up_to(world, stages, head_start)` call. 90s was chosen
# against Colonial Pipeline's 8x-compressed timeline (gates every ~30s):
# it pre-fires 3 of 12 gates, leaving 9 ahead of the player and ~390 of the
# 480s daily-mode budget still to play — "several compromised hosts", not
# a still-mostly-untouched map, and not "half the game already decided".
# Tunable by feel exactly like Scenario.compression_ratio; not adaptive
# per-scenario on purpose, to keep this a single, deterministic knob.
#
# Never allowed to reach/pass the scenario's own final (terminal) stage —
# see compile_scenario's clamp against final_stage.trigger_seconds - 1 —
# so a heavily-compressed or short scenario can never pre-fire its own
# loss condition before the player has taken a single action.
#
# Also never applied at all if nothing would actually fall within the
# window (see compile_scenario's any_stage_pre_fires check) — an
# uncompressed or sparsely-timed scenario whose earliest gate lands well
# past this constant has nothing to visibly pre-fire, so the effective
# head start (and the attacker_clock_offset shift verb_engine.new_run
# derives from it) both fall back to 0 rather than silently
# fast-forwarding every later stage for no visible reason at t=0.
BREACH_HEAD_START_SECONDS = 90


def _compress_seconds(raw_seconds: int, compression_ratio: float) -> int:
    """Scales an authored real-world timestamp (already converted to
    seconds) down to the action-console's compressed game clock. Colonial
    Pipeline's authored gates span +4m to +49m — real-incident pacing meant
    for the old tabletop mode's alert stream, not the 8/10-minute action-
    console caps (CAP_SECONDS_BY_MODE in action_run_store.py). Left
    unscaled, ~10 of 12 gates fell past every mode's cap and never fired in
    a playable session — this is the fix.

    Floors rather than rounds: a stage landing a second earlier than exact
    compression is harmless (the attacker just advances slightly sooner),
    while rounding UP risks pushing a stage past a cap it would otherwise
    have fit inside — exactly the failure mode this function exists to
    eliminate. Falls back to no compression (ratio 1.0) for a
    missing/non-positive authored ratio rather than raising or dividing by
    zero, consistent with this module's "bad authored content never crashes
    compilation" convention (see _parse_trigger_seconds).

    Deterministic: plain IEEE-754 double division followed by a floor, no
    RNG — the same (raw_seconds, compression_ratio) always produces the
    same integer on any platform, which is what Phase 4's "same seed, same
    run" ghost replay requires of every step compile_scenario takes."""
    ratio = compression_ratio if compression_ratio and compression_ratio > 0 else 1.0
    return int(raw_seconds // ratio)


def _parse_trigger_seconds(timestamp: str, compression_ratio: float = 1.0) -> int:
    """Parse an authored timestamp like '+4m' into elapsed seconds, then
    scale it by `compression_ratio` (see _compress_seconds). All authored
    content (backend/seed.py) uses '+Nm' (minutes); 's' is tolerated for
    forward-compatibility but unused today. Malformed/missing timestamps
    fall back to 0 rather than raising, so one bad authored field can't
    crash compilation — consistent with org_simulation.py's "never raises"
    style for content-derived input."""
    if not isinstance(timestamp, str):
        return 0
    m = _TIMESTAMP_RE.match(timestamp.strip())
    if not m:
        return 0
    value, unit = int(m.group(1)), m.group(2)
    raw_seconds = value * 60 if unit == "m" else value
    return _compress_seconds(raw_seconds, compression_ratio)


# industry_vertical -> _COMPILE_SCENARIO_ARCHETYPES key (ORG_ARCHETYPES
# plus DECISION_GATE_ARCHETYPES). Scenario.industry_vertical values not
# listed here (finance, government, retail, ...) fall back to
# _DEFAULT_ARCHETYPE_KEY rather than raising; this mapping widens
# gracefully as more archetypes are added without action_engine.py
# needing a matching change. New entries should target
# DECISION_GATE_ARCHETYPES unless the vertical is meant to also be a real
# Arena-mode archetype (see that dict's docstring in org_simulation.py).
_INDUSTRY_TO_ARCHETYPE: dict[str, str] = {
    # energy_utility_flagship, not energy_utility — Arena mode selects
    # "energy_utility" directly by archetype_key with its own size
    # balance; decision-gate content (Colonial Pipeline) needs a bigger
    # host_count_range for decoy-pool headroom (see org_simulation.py's
    # ORG_ARCHETYPES comments) and must not share that knob with Arena.
    "energy": "energy_utility_flagship",
    "critical_infrastructure": "energy_utility_flagship",
    "healthcare": "small_healthcare",
    "technology": "technology_saas",
    "hospitality": "hospitality_resort",
}
_DEFAULT_ARCHETYPE_KEY = "small_healthcare"


def _archetype_key_for_scenario(industry_vertical: Optional[str]) -> str:
    return _INDUSTRY_TO_ARCHETYPE.get(industry_vertical or "", _DEFAULT_ARCHETYPE_KEY)


def _field(scenario: ScenarioLike, name: str, default=None):
    """Read a field from either a plain dict or an ORM Scenario instance —
    compile_scenario accepts both so pytest can exercise it with a bare
    dict (see tests/test_action_engine.py) without a DB/ORM in the loop."""
    if isinstance(scenario, dict):
        return scenario.get(name, default)
    return getattr(scenario, name, default)


def _derive_rng(seed: int, salt: str) -> random.Random:
    """Deterministically derive a purpose-scoped RNG from (seed, salt), so
    e.g. the attack-path shuffle and the IOC placement draw from
    independent streams instead of accidentally sharing sequential state.
    Mirrors org_simulation._derive_rng's SHA-256-based derivation (avoids
    CPython's Random(x)/Random(-x) sign-symmetric collision risk)."""
    h = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


@dataclass(frozen=True)
class Stage:
    """One beat of the attacker's real, unopposed progression timeline.
    `compromises_host_ids` is what fires if the player hasn't contained the
    attack path by `trigger_seconds`: every listed host advances one
    compromise level. `is_final=True` marks the scenario's terminal impact
    event (exfil/encryption/detonation) — reaching it uncontained is the
    loss condition."""

    id: str
    trigger_seconds: int
    kind: str  # "decision_gate" | "pressure"
    source_id: str
    mitre_technique: Optional[str]
    compromises_host_ids: tuple[str, ...]
    is_final: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trigger_seconds": self.trigger_seconds,
            "kind": self.kind,
            "source_id": self.source_id,
            "mitre_technique": self.mitre_technique,
            "compromises_host_ids": list(self.compromises_host_ids),
            "is_final": self.is_final,
        }


@dataclass(frozen=True)
class IOCPlacement:
    """One hidden_iocs entry from the scenario, bound to a specific
    synthesized host_id so a future `query logs <host>` / `image disk
    <host>` verb can reveal it. Never sent to the client until earned.

    `matches_on` is the ORIGINAL scenario dict's matching hint (e.g.
    {"ip": "185.220.101.34"}) — kept for the verb layer's server-side
    `block ip <addr>` / future account-matching checks, which need the
    real authored identifier. It is deliberately excluded from `to_dict()`:
    `raw_log` (rewritten by _rewrite_raw_log_for_host) is what's safe to
    reveal to a player; `matches_on` never is, since for a hostname-type
    IOC it can literally be the answer to a later decision gate."""

    host_id: str
    description: str
    severity: str
    source_system: str
    rule_id: str
    raw_log: str
    matches_on: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "host_id": self.host_id,
            "description": self.description,
            "severity": self.severity,
            "source_system": self.source_system,
            "rule_id": self.rule_id,
            "raw_log": self.raw_log,
        }


@dataclass(frozen=True)
class MapEdge:
    source: str
    target: str

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target}


@dataclass(frozen=True)
class CompiledRun:
    """The full, server-only compiled scenario. `world`, `stages`, and
    every `IOCPlacement` are never sent to the client wholesale — building
    a redacted client-facing view is the WebSocket/route layer's job (the
    next Phase 2 commit), the same way arena.py's `_attacker_initial_view`/
    `_defender_initial_view` redact `OrgState` for Arena matches rather
    than org_simulation.py itself doing it."""

    scenario_id: str
    seed: int
    world: OrgState
    edges: tuple[MapEdge, ...]
    stages: tuple[Stage, ...]
    ioc_placements: tuple[IOCPlacement, ...]
    alert_lines: tuple[dict, ...]  # scenario alert_sequence w/ parsed trigger_seconds; ambient feed, not hidden
    final_stage_id: Optional[str]
    # Proportionate Response: the scenario's authored {hostname: weight}
    # collateral table (Scenario.collateral_weights), carried through
    # compilation the same way scenario_id already is, so verb_engine's
    # pure functions (_collateral_hosts/compute_score) never need their own
    # DB access — they read it off the CompiledRun like everything else.
    # `{}` for scenarios with none authored (MGM) or bare test-dict
    # fixtures without the field at all.
    collateral_weights: dict = field(default_factory=dict)
    # Phase 3 — Targeted Escalation & Notification Proportionality: the
    # scenario's authored [{id, party_name, warranted, ...}, ...] list
    # (Scenario.notification_matrix), carried through the same way
    # collateral_weights is above — verb_engine's escalate handler reads
    # this off the CompiledRun rather than needing its own DB access.
    # `()` for scenarios with none authored yet or bare test-dict fixtures
    # without the field at all.
    notification_matrix: tuple = field(default_factory=tuple)
    # How many (already-compressed) attacker-clock seconds are pre-folded
    # into `world` above — see BREACH_HEAD_START_SECONDS. `world_state_at`
    # and verb_engine.new_run both need this exact value (not just the
    # module constant) to avoid re-applying a stage that's already baked
    # in, since compile_scenario clamps it down for scenarios whose final
    # stage would otherwise fire before the run even starts.
    breach_head_start_seconds: int = 0


def _build_edges(state: OrgState) -> tuple[MapEdge, ...]:
    """Deterministic, presentation-only edge set for the network map: hosts
    chain within their own segment, and segments connect via one
    representative host-to-host edge per `reachable_from` relationship.
    Purely derived from `state` — no RNG, no scenario content, so it can
    never leak anything scenario-specific."""
    edges: list[MapEdge] = []
    hosts_by_segment: dict[str, list[Host]] = {}
    for h in state.hosts:
        hosts_by_segment.setdefault(h.network_segment_id, []).append(h)

    for hosts in hosts_by_segment.values():
        ordered = sorted(hosts, key=lambda h: h.id)
        for a, b in zip(ordered, ordered[1:]):
            edges.append(MapEdge(a.id, b.id))

    seen_segment_pairs: set[tuple[str, str]] = set()
    for seg in state.segments:
        for other_id in seg.reachable_from:
            pair = tuple(sorted((seg.id, other_id)))
            if pair in seen_segment_pairs:
                continue
            seen_segment_pairs.add(pair)
            a_hosts = sorted(hosts_by_segment.get(pair[0], []), key=lambda h: h.id)
            b_hosts = sorted(hosts_by_segment.get(pair[1], []), key=lambda h: h.id)
            if a_hosts and b_hosts:
                edges.append(MapEdge(a_hosts[0].id, b_hosts[0].id))

    return tuple(edges)


def _build_stages(
    decision_tree: list[dict],
    pressure_injections: list[dict],
    host_ids: list[str],
    seed: int,
    compression_ratio: float = 1.0,
    preferred_host_ids: tuple[str, ...] = (),
) -> tuple[Stage, ...]:
    """Deterministically converts decision_tree + pressure_injections into a
    sorted stage timeline. Each decision_gate stage advances the compromise
    level of a deterministically-chosen host from `host_ids` — an "attack
    path" built via a seeded RNG.

    `preferred_host_ids` (see host_harvest.py / docs/HOST_NAMESPACE_UNIFICATION_SPEC.md):
    an ordered tuple of host ids the attack path must run through first —
    every host a hidden_ioc names directly (matches_on.hostname), so that
    IOC's host is guaranteed to actually be on the attack path (investigating
    a visibly compromised host must be able to teach you something — see
    _place_iocs), followed by any other harvested (authored, not decoy)
    host. Only once every preferred host has appeared at least once does the
    path start cycling through the shuffled remainder (decoys, or — when
    nothing was harvested at all — every host, exactly the original
    behavior). This is what makes "read the alert, find the host on the
    map, query it" actually work: before host_harvest existed, the
    scenario's own free-text hostnames (e.g. "CORP-DC-01") had no reliable
    mapping to synthesized host ids at all.

    `compression_ratio` (the scenario's own field, see _compress_seconds)
    scales every authored trigger_timestamp before it ever becomes a
    trigger_seconds value here — max trigger_seconds selection, sort order,
    and everything downstream all operate on the already-compressed clock."""
    gates = [g for g in (decision_tree or []) if isinstance(g, dict)]
    gate_trigger_seconds = [
        _parse_trigger_seconds(g.get("trigger_timestamp", "+0m"), compression_ratio) for g in gates
    ]
    final_gate_index: Optional[int] = None
    if gate_trigger_seconds:
        final_gate_index = gate_trigger_seconds.index(max(gate_trigger_seconds))

    preferred = [h for h in preferred_host_ids if h in host_ids]
    remaining = [h for h in host_ids if h not in preferred]
    if remaining:
        _derive_rng(seed, "attack-path").shuffle(remaining)
    path: list[str] = preferred + remaining

    stages: list[Stage] = []
    for i, gate in enumerate(gates):
        target_host_ids: tuple[str, ...] = (path[i % len(path)],) if path else ()
        stages.append(Stage(
            id=f"stage-{gate.get('id', i + 1)}",
            trigger_seconds=gate_trigger_seconds[i],
            kind="decision_gate",
            source_id=str(gate.get("id", i)),
            mitre_technique=gate.get("mitre_technique"),
            compromises_host_ids=target_host_ids,
            is_final=(i == final_gate_index),
        ))

    for p in (pressure_injections or []):
        if not isinstance(p, dict):
            continue
        stages.append(Stage(
            id=f"stage-{p.get('id', 'pressure')}",
            trigger_seconds=_parse_trigger_seconds(p.get("trigger_timestamp", "+0m"), compression_ratio),
            kind="pressure",
            source_id=str(p.get("id", "")),
            mitre_technique=None,
            compromises_host_ids=(),
            is_final=False,
        ))

    stages.sort(key=lambda s: (s.trigger_seconds, s.kind != "decision_gate", s.id))
    return tuple(stages)


def _rewrite_raw_log_for_host(raw_log: str, matches_on: dict, host: Optional[Host]) -> str:
    """A hidden_ioc's raw_log is authored against the REAL scenario's own
    hostnames (e.g. "host=CORP-DC-01"), which don't exist in the
    synthesized world. Left as-is, revealed evidence would name a host that
    isn't on the player's network map — a direct contradiction. Rewrites
    every literal `matches_on["hostname"]` token in raw_log to the bound
    host's real synthesized hostname.

    `matches_on["ip"]` is deliberately LEFT UNTOUCHED. An IP in an IOC's
    raw_log identifies external attacker/C2 infrastructure, not a host on
    the map — there is no synthesized node for it to contradict. It's also
    the intended discovery path for the `block ip <addr>` verb
    (verb_engine.apply_verb), which checks a submitted address against this
    exact field: rewriting it away would erase the IP from every surface a
    player can ever see (raw_log is revealed; matches_on never is — see
    IOCPlacement), making a correct `block_ip` call unreachable through
    legitimate play. `matches_on` entries other than "hostname" (ip,
    "username", which identifies a Credential, not a Host) are left
    untouched here for the same "nothing on the map to contradict" reason."""
    if host is None:
        return raw_log
    token = matches_on.get("hostname")
    if token:
        raw_log = raw_log.replace(str(token), host.hostname)
    return raw_log


def _place_iocs(
    hidden_iocs: list[dict], world: OrgState, seed: int, stages: tuple[Stage, ...] = (),
) -> tuple[IOCPlacement, ...]:
    """Assigns each hidden_ioc to a synthesized host and rewrites its
    raw_log so the revealed evidence never contradicts the network map
    (see _rewrite_raw_log_for_host).

    A `matches_on.hostname`-keyed IOC binds DETERMINISTICALLY to the real
    host that authored hostname was harvested into (see host_harvest.py) —
    looked up by exact hostname match. This is the whole point of host
    namespace unification: the player who reads the alert naming this host
    and queries it on the map must find this specific evidence, not a
    random one. `compile_scenario` guarantees (via `_build_stages`'s
    `preferred_host_ids`) that a hostname-keyed IOC's host is always on the
    attack path, so this never violates the "must be on the attack path"
    invariant below even though it skips the random draw entirely.

    Every other hidden_ioc (matches_on keyed by ip/username/process_name,
    or a hostname that somehow isn't harvested — never happens for the 5
    flagship scenarios today, confirmed by harvest_report.py, but handled
    defensively) falls back to the original behavior: a seeded random
    choice among hosts a decision-gate stage actually compromises — the
    attack path — independent of _build_stages's own attack-path draw.
    Binding to the attack path (rather than any host in the world) is what
    makes investigating a compromised host actually teach something: a
    hidden_ioc landing on a host no stage ever touches means querying the
    host that's visibly being compromised could legitimately reveal
    nothing, while an untouched host held the evidence instead —
    disconnected from what the map is showing. Falls back to any host in
    the world if the attack path is empty (a scenario with no decision_tree
    gates has no attack path to bind to)."""
    host_ids = [h.id for h in world.hosts]
    if not host_ids:
        return ()

    # De-dup while preserving first-seen order (stages is already sorted by
    # trigger_seconds) so the candidate pool is deterministic and doesn't
    # over-weight a host multiple stages happen to compromise.
    seen: set[str] = set()
    candidate_ids: list[str] = []
    for s in stages:
        for hid in s.compromises_host_ids:
            if hid not in seen:
                seen.add(hid)
                candidate_ids.append(hid)
    if not candidate_ids:
        candidate_ids = host_ids

    hostname_to_id = {h.hostname: h.id for h in world.hosts}
    rng = _derive_rng(seed, "ioc-placement")
    placements: list[IOCPlacement] = []
    for ioc in (hidden_iocs or []):
        if not isinstance(ioc, dict):
            continue
        matches_on = ioc.get("matches_on") or {}
        named_host_id = hostname_to_id.get(matches_on.get("hostname"))
        host_id = named_host_id if named_host_id is not None else rng.choice(candidate_ids)
        host = world.get_host(host_id)
        placements.append(IOCPlacement(
            host_id=host_id,
            description=ioc.get("description", ""),
            severity=ioc.get("severity", "medium"),
            source_system=ioc.get("source_system", ""),
            rule_id=ioc.get("rule_id", ""),
            raw_log=_rewrite_raw_log_for_host(ioc.get("raw_log", ""), matches_on, host),
            matches_on=dict(matches_on),
        ))
    return tuple(placements)


def compile_scenario(scenario: ScenarioLike, seed: int) -> CompiledRun:
    """Deterministically compile a Scenario (ORM instance or a plain dict
    with the same field names) plus a seed into a CompiledRun. Same
    (scenario content, seed) always produces a byte-identical CompiledRun —
    verified by tests/test_action_engine.py's determinism tests.

    Host namespace unification (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md):
    hostnames the scenario's own authored content names (alert_sequence,
    hidden_iocs) are harvested and seeded as real map hosts — via
    host_harvest.build_host_plan — instead of the network map generating a
    disconnected namespace of its own with no reliable mapping back to
    what the player actually read.
    """
    scenario_id = str(_field(scenario, "id", ""))
    archetype_key = _archetype_key_for_scenario(_field(scenario, "industry_vertical"))
    archetype = _COMPILE_SCENARIO_ARCHETYPES[archetype_key]

    # The archetype-side term of host_harvest's elastic host-count formula
    # (max(archetype_roll, harvested+decoys)) needs its own seeded roll,
    # independent of generate_org_state's internal rng stream — which,
    # once a host_plan exists, never rolls host_count itself at all (see
    # generate_org_state's host_plan branch).
    archetype_host_lo, archetype_host_hi = archetype.get("host_count_range", [8, 10])
    archetype_host_roll = _derive_rng(seed, "archetype-host-roll").randint(
        int(archetype_host_lo), int(archetype_host_hi)
    )
    valid_segments = tuple(_SEGMENT_NAME_POOLS.get(
        archetype.get("industry_vertical", "default"), _SEGMENT_NAME_POOLS["default"]
    ))
    host_plan = host_harvest.build_host_plan(scenario, valid_segments, archetype_host_roll, seed)

    world = generate_org_state(seed, archetype, host_plan=host_plan)
    host_ids = [h.id for h in world.hosts]
    edges = _build_edges(world)

    decision_tree = _field(scenario, "decision_tree") or []
    pressure_injections = _field(scenario, "pressure_injections") or []
    hidden_iocs = _field(scenario, "hidden_iocs") or []
    alert_sequence = _field(scenario, "alert_sequence") or []
    # Scenario.compression_ratio (default 8.0 at the DB level) — see
    # _compress_seconds. Defaults to 1.0 (no scaling) for content that
    # doesn't carry the field at all, e.g. plain-dict test fixtures.
    compression_ratio = _field(scenario, "compression_ratio", 1.0)

    # Attack-path preference, in priority order: every host a hidden_ioc
    # names directly (guarantees that IOC's host lands on the attack path —
    # see _place_iocs), then any other harvested (authored, non-decoy) host.
    # Empty when host_plan is None (nothing harvested — e.g. a bare test
    # fixture), which reduces _build_stages back to its original
    # fully-shuffled behavior exactly.
    hostname_to_id = {h.hostname: h.id for h in world.hosts}
    ioc_hostnames = sorted(host_harvest.hostnames_referenced_by_hidden_iocs(scenario))
    required_ids = tuple(hostname_to_id[n] for n in ioc_hostnames if n in hostname_to_id)
    harvested_ids = tuple(
        hid for hid in (
            hostname_to_id.get(entry["hostname"]) for entry in (host_plan or []) if entry["is_harvested"]
        )
        if hid is not None and hid not in required_ids
    )
    preferred_host_ids = required_ids + harvested_ids

    stages = _build_stages(decision_tree, pressure_injections, host_ids, seed, compression_ratio, preferred_host_ids)
    ioc_placements = _place_iocs(hidden_iocs, world, seed, stages)

    alert_lines = tuple(
        {**a, "trigger_seconds": _parse_trigger_seconds(a.get("timestamp", "+0m"), compression_ratio)}
        for a in alert_sequence
        if isinstance(a, dict)
    )

    final_stage = next((s for s in stages if s.is_final), None)
    final_stage_id = final_stage.id if final_stage is not None else None

    # "Incident already in progress" fix (see BREACH_HEAD_START_SECONDS):
    # clamped below the final stage's own trigger_seconds so a heavily-
    # compressed or short scenario can never pre-fire its own terminal
    # event — the player always has an active, not-yet-lost run to walk
    # into, however small BREACH_HEAD_START_SECONDS ends up mattering here.
    if final_stage is not None:
        candidate_head_start = min(BREACH_HEAD_START_SECONDS, max(final_stage.trigger_seconds - 1, 0))
    else:
        candidate_head_start = BREACH_HEAD_START_SECONDS
    # ... but only actually apply it if some decision_gate stage genuinely
    # falls within that window. A scenario whose earliest gate lands well
    # past BREACH_HEAD_START_SECONDS (or one with no gates at all) has
    # nothing to visibly pre-fire — falling back to a "head start" that
    # compromises zero hosts would still shift verb_engine.new_run's
    # attacker_clock_offset (see that function), quietly fast-forwarding
    # every LATER stage for no visible reason at t=0. Keeping the two in
    # lockstep (a real head start iff something actually got pre-fired)
    # is what lets scenarios/fixtures with a sparse or distant timeline
    # opt out for free, with no separate flag needed.
    any_stage_pre_fires = any(
        s.trigger_seconds <= candidate_head_start and s.compromises_host_ids for s in stages
    )
    breach_head_start_seconds = candidate_head_start if any_stage_pre_fires else 0
    world = _apply_stages_up_to(world, stages, breach_head_start_seconds)

    collateral_weights = _field(scenario, "collateral_weights") or {}
    notification_matrix = tuple(_field(scenario, "notification_matrix") or ())

    return CompiledRun(
        scenario_id=scenario_id,
        seed=seed,
        world=world,
        edges=edges,
        stages=stages,
        ioc_placements=ioc_placements,
        alert_lines=alert_lines,
        final_stage_id=final_stage_id,
        collateral_weights=collateral_weights,
        notification_matrix=notification_matrix,
        breach_head_start_seconds=breach_head_start_seconds,
    )


def _apply_stages_up_to(
    world: OrgState, stages: tuple[Stage, ...], elapsed_seconds: int, already_applied_through: int = 0,
) -> OrgState:
    """Applies every stage whose trigger_seconds falls in
    (already_applied_through, elapsed_seconds] against `world`, advancing
    each targeted host's compromise_level by one step (never past
    domain_admin, never onto an isolated host — there is none to isolate
    yet at compile time, but this is shared with world_state_at's general
    case). `already_applied_through` lets a caller skip stages that are
    already folded into `world`'s own baseline (see compile_scenario's
    BREACH_HEAD_START_SECONDS pre-fire) instead of re-applying them and
    double-advancing a host. Pure and deterministic: same inputs always
    produce a byte-identical OrgState."""
    state = world
    for stage in stages:
        if stage.trigger_seconds <= already_applied_through:
            continue
        if stage.trigger_seconds > elapsed_seconds:
            continue
        for host_id in stage.compromises_host_ids:
            host = state.get_host(host_id)
            if host is None or host.isolated:
                continue
            current_index = _COMPROMISE_LEVELS.index(host.compromise_level)
            next_level = _COMPROMISE_LEVELS[min(current_index + 1, len(_COMPROMISE_LEVELS) - 1)]
            if next_level == host.compromise_level:
                continue
            new_hosts = tuple(
                (replace(h, compromise_level=next_level) if h.id == host_id else h)
                for h in state.hosts
            )
            state = OrgState(
                hosts=new_hosts,
                segments=state.segments,
                credentials=state.credentials,
                detection_rules=state.detection_rules,
                global_flags=state.global_flags,
            )
    return state


def world_state_at(compiled: CompiledRun, elapsed_seconds: int) -> OrgState:
    """Pure: the hidden OrgState if the attacker has been completely
    unopposed from 0 to `elapsed_seconds` — every stage whose
    trigger_seconds <= elapsed_seconds has fired and applied its host
    compromise. This is the baseline, no-defender-action timeline; the
    later verb-application layer (isolate/etc.) applies defender actions on
    top of it, the same way org_simulation.apply_defender_action does for
    Arena. Deterministic and pure: same (compiled, elapsed_seconds) always
    produces a byte-identical OrgState.

    `compiled.world` already has every stage through
    `compiled.breach_head_start_seconds` folded in at compile time (the
    "incident already in progress" fix — see BREACH_HEAD_START_SECONDS), so
    `world_state_at(compiled, 0)` returns that pre-fired state directly
    rather than a pristine, all-clean world."""
    return _apply_stages_up_to(
        compiled.world, compiled.stages, elapsed_seconds,
        already_applied_through=compiled.breach_head_start_seconds,
    )
