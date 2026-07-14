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
from dataclasses import dataclass, replace
from typing import Optional, Union

from app.services.org_simulation import (
    ORG_ARCHETYPES,
    Host,
    OrgState,
    generate_org_state,
)

ScenarioLike = Union[dict, object]  # ORM Scenario instance, or a plain dict with the same field names

_TIMESTAMP_RE = re.compile(r'^\+(\d+)([ms])$')

# compromise_level progression order — mirrors org_simulation._COMPROMISE_ORDER,
# duplicated locally since that name is private to org_simulation.py.
_COMPROMISE_LEVELS = ("none", "foothold", "admin", "domain_admin")


def _parse_trigger_seconds(timestamp: str) -> int:
    """Parse an authored timestamp like '+4m' into elapsed seconds. All
    authored content (backend/seed.py) uses '+Nm' (minutes); 's' is
    tolerated for forward-compatibility but unused today. Malformed/missing
    timestamps fall back to 0 rather than raising, so one bad authored
    field can't crash compilation — consistent with org_simulation.py's
    "never raises" style for content-derived input."""
    if not isinstance(timestamp, str):
        return 0
    m = _TIMESTAMP_RE.match(timestamp.strip())
    if not m:
        return 0
    value, unit = int(m.group(1)), m.group(2)
    return value * 60 if unit == "m" else value


# industry_vertical -> ORG_ARCHETYPES key. Scenario.industry_vertical values
# not listed here (finance, government, technology, retail, ...) fall back to
# _DEFAULT_ARCHETYPE_KEY rather than raising — ORG_ARCHETYPES only has two
# entries today (Arena Phase A); this mapping widens gracefully as more
# archetypes are added without action_engine.py needing a matching change.
_INDUSTRY_TO_ARCHETYPE: dict[str, str] = {
    "energy": "energy_utility",
    "critical_infrastructure": "energy_utility",
    "healthcare": "small_healthcare",
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
    <host>` verb can reveal it. Never sent to the client until earned."""

    host_id: str
    description: str
    severity: str
    source_system: str
    rule_id: str
    raw_log: str

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
) -> tuple[Stage, ...]:
    """Deterministically converts decision_tree + pressure_injections into a
    sorted stage timeline. Each decision_gate stage advances the compromise
    level of a deterministically-chosen host from `host_ids` — an "attack
    path" built via a seeded RNG, since the scenario's own free-text
    hostnames (e.g. "CORP-DC-01") don't correspond to synthesized host ids
    and have no reliable mapping to them. Pressure stages carry no host
    compromise; they're timeline beats only. The LAST authored decision_tree
    gate (by array order — seed.py's gates are already chronological) is
    the terminal, `is_final` stage."""
    gates = [g for g in (decision_tree or []) if isinstance(g, dict)]

    path: list[str] = list(host_ids)
    if path:
        _derive_rng(seed, "attack-path").shuffle(path)

    stages: list[Stage] = []
    for i, gate in enumerate(gates):
        target_host_ids: tuple[str, ...] = (path[i % len(path)],) if path else ()
        stages.append(Stage(
            id=f"stage-{gate.get('id', i + 1)}",
            trigger_seconds=_parse_trigger_seconds(gate.get("trigger_timestamp", "+0m")),
            kind="decision_gate",
            source_id=str(gate.get("id", i)),
            mitre_technique=gate.get("mitre_technique"),
            compromises_host_ids=target_host_ids,
            is_final=(i == len(gates) - 1),
        ))

    for p in (pressure_injections or []):
        if not isinstance(p, dict):
            continue
        stages.append(Stage(
            id=f"stage-{p.get('id', 'pressure')}",
            trigger_seconds=_parse_trigger_seconds(p.get("trigger_timestamp", "+0m")),
            kind="pressure",
            source_id=str(p.get("id", "")),
            mitre_technique=None,
            compromises_host_ids=(),
            is_final=False,
        ))

    stages.sort(key=lambda s: (s.trigger_seconds, s.kind != "decision_gate", s.id))
    return tuple(stages)


def _place_iocs(hidden_iocs: list[dict], host_ids: list[str], seed: int) -> tuple[IOCPlacement, ...]:
    """Deterministically assigns each hidden_ioc to a synthesized host, via
    a seeded RNG independent of _build_stages's attack-path draw."""
    if not host_ids:
        return ()
    rng = _derive_rng(seed, "ioc-placement")
    placements: list[IOCPlacement] = []
    for ioc in (hidden_iocs or []):
        if not isinstance(ioc, dict):
            continue
        placements.append(IOCPlacement(
            host_id=rng.choice(host_ids),
            description=ioc.get("description", ""),
            severity=ioc.get("severity", "medium"),
            source_system=ioc.get("source_system", ""),
            rule_id=ioc.get("rule_id", ""),
            raw_log=ioc.get("raw_log", ""),
        ))
    return tuple(placements)


def compile_scenario(scenario: ScenarioLike, seed: int) -> CompiledRun:
    """Deterministically compile a Scenario (ORM instance or a plain dict
    with the same field names) plus a seed into a CompiledRun. Same
    (scenario content, seed) always produces a byte-identical CompiledRun —
    verified by tests/test_action_engine.py's determinism tests.
    """
    scenario_id = str(_field(scenario, "id", ""))
    archetype_key = _archetype_key_for_scenario(_field(scenario, "industry_vertical"))
    archetype = ORG_ARCHETYPES[archetype_key]

    world = generate_org_state(seed, archetype)
    host_ids = [h.id for h in world.hosts]
    edges = _build_edges(world)

    decision_tree = _field(scenario, "decision_tree") or []
    pressure_injections = _field(scenario, "pressure_injections") or []
    hidden_iocs = _field(scenario, "hidden_iocs") or []
    alert_sequence = _field(scenario, "alert_sequence") or []

    stages = _build_stages(decision_tree, pressure_injections, host_ids, seed)
    ioc_placements = _place_iocs(hidden_iocs, host_ids, seed)

    alert_lines = tuple(
        {**a, "trigger_seconds": _parse_trigger_seconds(a.get("timestamp", "+0m"))}
        for a in alert_sequence
        if isinstance(a, dict)
    )

    final_stage_id = next((s.id for s in stages if s.is_final), None)

    return CompiledRun(
        scenario_id=scenario_id,
        seed=seed,
        world=world,
        edges=edges,
        stages=stages,
        ioc_placements=ioc_placements,
        alert_lines=alert_lines,
        final_stage_id=final_stage_id,
    )


def world_state_at(compiled: CompiledRun, elapsed_seconds: int) -> OrgState:
    """Pure: the hidden OrgState if the attacker has been completely
    unopposed from 0 to `elapsed_seconds` — every stage whose
    trigger_seconds <= elapsed_seconds has fired and applied its host
    compromise. This is the baseline, no-defender-action timeline; the
    later verb-application layer (isolate/etc.) applies defender actions on
    top of it, the same way org_simulation.apply_defender_action does for
    Arena. Deterministic and pure: same (compiled, elapsed_seconds) always
    produces a byte-identical OrgState."""
    state = compiled.world
    for stage in compiled.stages:
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
