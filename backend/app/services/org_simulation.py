"""Live Arena Mode: the Org Simulation Engine.

Phase A placeholder (the `ORG_ARCHETYPES` constant) plus Phase B: the
deterministic, pure-function simulation core described in
docs/plans/live-arena-mode.md, "Architecture: the Org Simulation Engine".

`ArenaOrgArchetype` defaults to a Python constant (not a DB table) for v1 —
non-engineers don't need to author archetypes yet, and a table can be
introduced later without touching ArenaMatch/ArenaAction, since matches only
reference archetypes by string key (`ArenaMatch.archetype_key`).

Design notes (Phase B):
- Every entity is a frozen (immutable) dataclass. Every state-changing
  function returns a NEW `OrgState` (new tuples of new entity instances)
  rather than mutating anything in place. This is deliberate, not just
  style: Phase G's future branching replay needs to fork state at any
  checkpoint, which only works cleanly if past `OrgState` snapshots can
  never be silently mutated out from under a reference held elsewhere.
- Determinism is the entire point of the feature. Nothing in this module
  may call the global `random` module's top-level functions
  (`random.random()`, `random.choice()`, `random.randint()`, etc.) without
  going through a `random.Random(seed)` instance created and threaded
  through explicitly by the caller. `replay()` derives a fresh, per-action
  `random.Random` from `(seed, sequence_number)` so that replaying the same
  action log twice — or replaying a shorter prefix of it, per Phase G's
  "what if I'd chosen differently at step N" — is byte-identical up to the
  point of divergence.
- Dataclasses (not Pydantic) were chosen deliberately even though the rest
  of this codebase's `app/schemas/` uses Pydantic `BaseModel` for API I/O
  boundaries (see `app/schemas/session.py`). Pydantic models there exist to
  validate/serialize request and response bodies at the FastAPI edge.
  `OrgState` is never an API boundary in this phase (no routes are added
  here) — it's an internal simulation object graph that needs to be cheap
  to construct thousands of times in a fuzz loop, trivially comparable via
  equality for the determinism tests, and easy to freeze. (Note: `OrgState`
  is NOT hashable — `global_flags: dict` makes `hash(OrgState())` raise
  `TypeError` — equality comparison via `==`/`to_dict()` is what the
  determinism tests actually rely on.) Plain
  `@dataclass(frozen=True)` with small `to_dict`/`from_dict` helpers (using
  `dataclasses.asdict` under the hood) satisfies the "trivially convertible
  to/from plain dicts for JSONB storage" requirement without pulling in
  Pydantic's validation machinery for a purely internal type. If a later
  phase exposes `OrgState` directly over the API, converting the edge layer
  to Pydantic at that point is a small, local change.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal, Optional


# ── Phase A: archetype constant (unchanged) ────────────────────────────────

# Archetypes for generate_org_state(seed, archetype) to consume. Keep the
# vocabulary consistent with the existing Scenario.industry_vertical /
# difficulty fields so arena mode reuses the same industry/difficulty
# language as the authored scenario library.
ORG_ARCHETYPES: dict[str, dict] = {
    "small_healthcare": {
        "industry_vertical": "healthcare",
        "difficulty": "beginner",
        "size": "small",
        "host_count_range": [8, 10],
        "segment_count_range": [2, 2],
        "security_maturity": "low",
    },
    "energy_utility": {
        "industry_vertical": "energy",
        "difficulty": "advanced",
        "size": "large",
        "host_count_range": [12, 15],
        "segment_count_range": [3, 3],
        "security_maturity": "medium",
    },
}


# ── Phase B: entity model ───────────────────────────────────────────────────

CompromiseLevel = Literal["none", "foothold", "admin", "domain_admin"]
Privilege = Literal["user", "admin", "domain_admin"]
HostRole = Literal["workstation", "domain_controller", "server", "scada"]

_COMPROMISE_ORDER: dict[str, int] = {"none": 0, "foothold": 1, "admin": 2, "domain_admin": 3}


@dataclass(frozen=True)
class Host:
    id: str
    hostname: str
    role: HostRole
    network_segment_id: str
    unpatched_cves: tuple[str, ...] = ()
    edr_installed: bool = False
    compromise_level: CompromiseLevel = "none"
    isolated: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["unpatched_cves"] = list(self.unpatched_cves)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Host":
        d = dict(d)
        d["unpatched_cves"] = tuple(d.get("unpatched_cves") or ())
        return Host(**d)


@dataclass(frozen=True)
class NetworkSegment:
    id: str
    name: str
    monitored: bool = False
    reachable_from: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reachable_from"] = list(self.reachable_from)
        return d

    @staticmethod
    def from_dict(d: dict) -> "NetworkSegment":
        d = dict(d)
        d["reachable_from"] = tuple(d.get("reachable_from") or ())
        return NetworkSegment(**d)


@dataclass(frozen=True)
class Credential:
    id: str
    username: str
    privilege: Privilege
    valid_on_host_ids: tuple[str, ...] = ()
    harvested: bool = False
    disabled: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["valid_on_host_ids"] = list(self.valid_on_host_ids)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Credential":
        d = dict(d)
        d["valid_on_host_ids"] = tuple(d.get("valid_on_host_ids") or ())
        return Credential(**d)


@dataclass(frozen=True)
class DetectionRule:
    id: str
    technique_id: str
    applies_to_role: Optional[str] = None
    requires_edr: bool = False
    requires_monitored_segment: bool = False
    base_detection_probability: float = 0.2

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DetectionRule":
        return DetectionRule(**d)


@dataclass(frozen=True)
class OrgState:
    hosts: tuple[Host, ...] = ()
    segments: tuple[NetworkSegment, ...] = ()
    credentials: tuple[Credential, ...] = ()
    detection_rules: tuple[DetectionRule, ...] = ()
    global_flags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hosts": [h.to_dict() for h in self.hosts],
            "segments": [s.to_dict() for s in self.segments],
            "credentials": [c.to_dict() for c in self.credentials],
            "detection_rules": [r.to_dict() for r in self.detection_rules],
            "global_flags": dict(self.global_flags),
        }

    @staticmethod
    def from_dict(d: dict) -> "OrgState":
        return OrgState(
            hosts=tuple(Host.from_dict(h) for h in d.get("hosts", [])),
            segments=tuple(NetworkSegment.from_dict(s) for s in d.get("segments", [])),
            credentials=tuple(Credential.from_dict(c) for c in d.get("credentials", [])),
            detection_rules=tuple(DetectionRule.from_dict(r) for r in d.get("detection_rules", [])),
            global_flags=dict(d.get("global_flags", {})),
        )

    # ── convenience lookups (read-only; do not mutate) ──────────────────
    def get_host(self, host_id: str) -> Optional[Host]:
        return next((h for h in self.hosts if h.id == host_id), None)

    def get_segment(self, segment_id: str) -> Optional[NetworkSegment]:
        return next((s for s in self.segments if s.id == segment_id), None)

    def get_credential(self, credential_id: str) -> Optional[Credential]:
        return next((c for c in self.credentials if c.id == credential_id), None)


# ── Generation ───────────────────────────────────────────────────────────────

_SEGMENT_NAME_POOLS: dict[str, list[str]] = {
    "energy": ["corp", "dmz", "ot"],
    "healthcare": ["corp", "dmz", "clinical"],
    "default": ["corp", "dmz", "server"],
}

# Roles eligible per industry vertical. scada is only ever generated for
# archetypes whose industry_vertical plausibly has an OT/ICS footprint —
# energy always, healthcare only if explicitly flagged via
# archetype["has_ot"] (none of the current archetypes set this, so
# small_healthcare never generates scada hosts today; this keeps the door
# open for a future "hospital with OT-connected devices" archetype without
# a schema change).
_SCADA_VERTICALS = {"energy"}

_NON_SCADA_ROLES: tuple[HostRole, ...] = ("workstation", "domain_controller", "server")

# security_maturity -> (unpatched CVE probability per host, EDR coverage
# probability per host, fraction of segments monitored). Higher maturity =
# fewer unpatched CVEs, more EDR, more monitored segments, per the plan.
_MATURITY_PARAMS: dict[str, dict] = {
    "low": {"cve_prob": 0.55, "edr_prob": 0.35, "monitored_frac": 0.34},
    "medium": {"cve_prob": 0.30, "edr_prob": 0.65, "monitored_frac": 0.67},
    "high": {"cve_prob": 0.10, "edr_prob": 0.90, "monitored_frac": 1.0},
}

_SAMPLE_CVES = [
    "CVE-2021-34527",  # PrintNightmare
    "CVE-2020-1472",   # Zerologon
    "CVE-2017-0144",   # EternalBlue / MS17-010
    "CVE-2021-44228",  # Log4Shell
    "CVE-2019-0708",   # BlueKeep
    "CVE-2022-30190",  # Follina
]

_SAMPLE_USERNAMES = [
    "jsmith", "svc_backup", "svc_sql", "mchen", "administrator",
    "svc_update01", "rwilliams", "helpdesk_admin", "svc_reporting", "tlee",
]

# Detection rules cover common technique categories, reusing
# redteam.py's PHASE_MOVES technique_id vocabulary so arena alerts read
# consistently with solo Red Team Mode's flavor text.
_DETECTION_RULE_TEMPLATES: list[dict] = [
    {"technique_id": "T1078", "applies_to_role": None, "requires_edr": False, "requires_monitored_segment": True, "base_detection_probability": 0.2},
    {"technique_id": "T1003.001", "applies_to_role": None, "requires_edr": True, "requires_monitored_segment": False, "base_detection_probability": 0.5},
    {"technique_id": "T1021.001", "applies_to_role": None, "requires_edr": False, "requires_monitored_segment": True, "base_detection_probability": 0.4},
    {"technique_id": "T1550.002", "applies_to_role": None, "requires_edr": True, "requires_monitored_segment": True, "base_detection_probability": 0.45},
    {"technique_id": "T1486", "applies_to_role": None, "requires_edr": True, "requires_monitored_segment": False, "base_detection_probability": 0.6},
    {"technique_id": "T1046", "applies_to_role": None, "requires_edr": False, "requires_monitored_segment": True, "base_detection_probability": 0.3},
]


def generate_org_state(seed: int, archetype: dict) -> OrgState:
    """Deterministically build a small OrgState from an archetype config.

    Uses a local `random.Random(seed)` instance exclusively — never the
    global `random` module — so the same (seed, archetype) always produces
    a byte-identical OrgState.
    """
    rng = random.Random(seed)

    industry = archetype.get("industry_vertical", "default")
    maturity = archetype.get("security_maturity", "medium")
    params = _MATURITY_PARAMS.get(maturity, _MATURITY_PARAMS["medium"])

    host_lo, host_hi = archetype.get("host_count_range", [8, 10])
    seg_lo, seg_hi = archetype.get("segment_count_range", [2, 2])

    host_count = rng.randint(int(host_lo), int(host_hi))
    segment_count = rng.randint(int(seg_lo), int(seg_hi))

    # ── segments ──
    name_pool = _SEGMENT_NAME_POOLS.get(industry, _SEGMENT_NAME_POOLS["default"])
    segments: list[NetworkSegment] = []
    monitored_count = round(segment_count * params["monitored_frac"])
    for i in range(segment_count):
        base_name = name_pool[i] if i < len(name_pool) else f"segment-{i+1}"
        seg_id = f"seg-{i+1}"
        # Coarse reachability model: every segment is reachable from every
        # other segment except itself, EXCEPT an "ot"/"scada"-flavored
        # segment (present only for scada-eligible industries), which is
        # reachable only from "corp" — a simple, deliberately coarse
        # firewall model per the plan's explicit "no real packet
        # simulation" scope guard.
        segments.append(NetworkSegment(
            id=seg_id,
            name=base_name,
            monitored=(i < monitored_count),
            reachable_from=tuple(f"seg-{j+1}" for j in range(segment_count) if j != i),
        ))
    if industry in _SCADA_VERTICALS and segment_count >= 2:
        ot_index = len(segments) - 1
        corp_seg_id = segments[0].id
        segments[ot_index] = NetworkSegment(
            id=segments[ot_index].id,
            name="ot",
            monitored=segments[ot_index].monitored,
            reachable_from=(corp_seg_id,),
        )

    # ── hosts ──
    roles: list[HostRole] = list(_NON_SCADA_ROLES)
    if industry in _SCADA_VERTICALS:
        roles = list(_NON_SCADA_ROLES) + ["scada"]

    hosts: list[Host] = []
    dc_placed = False
    for i in range(host_count):
        seg = segments[i % len(segments)]
        if not dc_placed and i == 0:
            role: HostRole = "domain_controller"
            dc_placed = True
        elif seg.name == "ot" and industry in _SCADA_VERTICALS:
            role = "scada" if rng.random() < 0.6 else "server"
        else:
            role = rng.choice([r for r in roles if r != "scada"])

        unpatched = tuple(
            cve for cve in _SAMPLE_CVES
            if rng.random() < (params["cve_prob"] / max(1, len(_SAMPLE_CVES) // 3))
        )
        edr_installed = rng.random() < params["edr_prob"]

        hosts.append(Host(
            id=f"host-{i+1}",
            hostname=f"{seg.name.upper()}-{role.upper()[:3]}-{i+1:02d}",
            role=role,
            network_segment_id=seg.id,
            unpatched_cves=unpatched,
            edr_installed=edr_installed,
            compromise_level="none",
            isolated=False,
        ))

    host_ids = [h.id for h in hosts]

    # ── credentials ──
    cred_count = max(3, host_count // 3)
    credentials: list[Credential] = []
    for i in range(cred_count):
        username = _SAMPLE_USERNAMES[i % len(_SAMPLE_USERNAMES)]
        if username == "administrator" or username.startswith("svc_update"):
            privilege: Privilege = "domain_admin"
        elif username.startswith("svc_"):
            privilege = "admin"
        else:
            privilege = "user"

        # Credential reuse: each credential is valid on a random subset of
        # hosts (at least 1, up to a third of the org) — deliberate overlap
        # across hosts is what makes lateral movement/pass-the-hash
        # strategically interesting.
        valid_count = rng.randint(1, max(1, host_count // 3))
        valid_on = tuple(rng.sample(host_ids, k=min(valid_count, len(host_ids))))

        credentials.append(Credential(
            id=f"cred-{i+1}",
            username=username,
            privilege=privilege,
            valid_on_host_ids=valid_on,
            harvested=False,
            disabled=False,
        ))

    # ── detection rules ──
    detection_rules = tuple(
        DetectionRule(id=f"rule-{i+1}", **tmpl)
        for i, tmpl in enumerate(_DETECTION_RULE_TEMPLATES)
    )

    return OrgState(
        hosts=tuple(hosts),
        segments=tuple(segments),
        credentials=tuple(credentials),
        detection_rules=detection_rules,
        global_flags={"backups_immutable": maturity == "high"},
    )


# ── Action vocabulary ───────────────────────────────────────────────────────
#
# Kept deliberately small for v1. Payloads are plain JSON-serializable
# dicts matching ArenaAction.action_type / ArenaAction.payload
# (backend/app/models/arena.py). Target/reference IDs are carried in the
# payload; there is no implicit "current position" state beyond what's
# encoded in OrgState itself (e.g. a host's compromise_level).
#
# Attacker action_types:
#   discover_segment   {segment_id}
#   discover_host      {host_id}
#   gain_foothold      {host_id}
#   dump_credentials   {host_id}
#   escalate_privilege {host_id}
#   lateral_move       {credential_id, target_host_id}
#   deploy_impact      {host_id}                (match-ending; ransomware/exfil-equivalent)
#
# Defender action_types:
#   isolate_host       {host_id}
#   disable_credential {credential_id}
#   patch_host         {host_id, cve: optional str}  (omit cve to patch all)
#   increase_monitoring {segment_id}
#   acknowledge        {}                        (no-op, always succeeds)

ATTACKER_ACTION_TYPES = (
    "discover_segment",
    "discover_host",
    "gain_foothold",
    "dump_credentials",
    "escalate_privilege",
    "lateral_move",
    "deploy_impact",
)

DEFENDER_ACTION_TYPES = (
    "isolate_host",
    "disable_credential",
    "patch_host",
    "increase_monitoring",
    "acknowledge",
)

# action_type -> representative MITRE technique_id, reusing redteam.py's
# PHASE_MOVES vocabulary so alerts read consistently with solo Red Team
# Mode. Used only for alert flavor / detection-rule matching, not gameplay
# logic.
_ACTION_TECHNIQUE_IDS: dict[str, str] = {
    "discover_segment": "T1046",
    "discover_host": "T1046",
    "gain_foothold": "T1078",
    "dump_credentials": "T1003.001",
    "escalate_privilege": "T1068",
    "lateral_move": "T1550.002",
    "deploy_impact": "T1486",
}


def _replace_host(state: OrgState, host_id: str, **changes) -> OrgState:
    """Return a new OrgState with one Host replaced by a modified copy.
    Pure — never mutates `state` or any entity in it."""
    new_hosts = tuple(
        (Host(**{**asdict(h), "unpatched_cves": h.unpatched_cves, **changes}) if h.id == host_id else h)
        for h in state.hosts
    )
    return OrgState(
        hosts=new_hosts,
        segments=state.segments,
        credentials=state.credentials,
        detection_rules=state.detection_rules,
        global_flags=state.global_flags,
    )


def _replace_credential(state: OrgState, credential_id: str, **changes) -> OrgState:
    new_creds = tuple(
        (Credential(**{**asdict(c), "valid_on_host_ids": c.valid_on_host_ids, **changes}) if c.id == credential_id else c)
        for c in state.credentials
    )
    return OrgState(
        hosts=state.hosts,
        segments=state.segments,
        credentials=new_creds,
        detection_rules=state.detection_rules,
        global_flags=state.global_flags,
    )


def _is_host_reachable(state: OrgState, host: Host) -> bool:
    """A host is reachable to the attacker if it isn't isolated. Segment
    reachability (reachable_from) governs lateral movement BETWEEN
    segments; a directly-targeted host that isn't isolated is always
    reachable for the initial foothold/discovery actions."""
    return not host.isolated


def _segment_reachable_from_any_compromised(state: OrgState, target_segment_id: str) -> bool:
    """True if `target_segment_id` is reachable from the segment of any
    currently-compromised, non-isolated host (coarse firewall model, no
    packet-level simulation per the plan's scope guard)."""
    target_seg = state.get_segment(target_segment_id)
    if target_seg is None:
        return False
    compromised_segment_ids = {
        h.network_segment_id
        for h in state.hosts
        if h.compromise_level != "none" and not h.isolated
    }
    if target_seg.id in compromised_segment_ids:
        return True
    return any(seg_id in target_seg.reachable_from for seg_id in compromised_segment_ids)


def _build_alert(rule: DetectionRule, host: Optional[Host], sequence_number: int, description: str, raw_log: str, severity: str = "medium") -> dict:
    """Build an alert dict matching the existing seed.py alert_sequence shape:
    {timestamp, severity, source_system, rule_id, description, raw_log}."""
    return {
        "timestamp": f"+{sequence_number}m",
        "severity": severity,
        "source_system": "EDR" if rule.requires_edr else "SIEM",
        "rule_id": rule.id,
        "description": description,
        "raw_log": raw_log,
    }


def _detect(state: OrgState, technique_id: str, host: Optional[Host], segment: Optional[NetworkSegment], rng: random.Random) -> Optional[DetectionRule]:
    """Check applicable DetectionRules for `technique_id` against the
    affected host/segment; return the first rule that fires, else None.
    Uses the passed-in rng exclusively."""
    for rule in state.detection_rules:
        if rule.technique_id != technique_id:
            continue
        if rule.applies_to_role and (host is None or host.role != rule.applies_to_role):
            continue
        if rule.requires_edr and not (host and host.edr_installed):
            continue
        if rule.requires_monitored_segment and not (segment and segment.monitored):
            continue
        if rng.random() < rule.base_detection_probability:
            return rule
    return None


def apply_attacker_action(state: OrgState, action: dict, rng: random.Random) -> tuple[OrgState, bool, Optional[dict]]:
    """Apply an attacker action against the real OrgState object graph.

    Returns (new_state, detected, alert). Invalid/unmet-precondition
    actions fail gracefully: state is returned unchanged, detected=False,
    alert=None — never raises. This includes a non-dict `action` (e.g.
    None, a string, or a list from a malformed action log).
    """
    if not isinstance(action, dict):
        return state, False, None

    action_type = action.get("action_type")
    payload = action.get("payload", action)  # tolerate flat or nested payload
    sequence_number = action.get("sequence_number", 0)
    technique_id = _ACTION_TECHNIQUE_IDS.get(action_type, "T1000")

    if action_type not in ATTACKER_ACTION_TYPES:
        return state, False, None

    # discover_segment / discover_host are recon-only: no state change,
    # but they DO carry detection risk (matches T1046 in redteam.py).
    if action_type == "discover_segment":
        segment_id = payload.get("segment_id")
        segment = state.get_segment(segment_id)
        if segment is None:
            return state, False, None
        rule = _detect(state, technique_id, None, segment, rng)
        if rule:
            alert = _build_alert(
                rule, None, sequence_number,
                f"Network scan activity detected touching segment '{segment.name}'",
                f"scan_target=segment:{segment.id} monitored={segment.monitored}",
            )
            return state, True, alert
        return state, False, None

    if action_type == "discover_host":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None:
            return state, False, None
        segment = state.get_segment(host.network_segment_id)
        rule = _detect(state, technique_id, host, segment, rng)
        if rule:
            alert = _build_alert(
                rule, host, sequence_number,
                f"Host enumeration touched {host.hostname}",
                f"scan_target=host:{host.id} host={host.hostname}",
            )
            return state, True, alert
        return state, False, None

    if action_type == "gain_foothold":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or host.isolated or host.compromise_level != "none":
            return state, False, None
        new_state = _replace_host(state, host_id, compromise_level="foothold")
        segment = state.get_segment(host.network_segment_id)
        rule = _detect(state, technique_id, host, segment, rng)
        alert = None
        if rule:
            alert = _build_alert(
                rule, host, sequence_number,
                f"Suspicious initial-access activity on {host.hostname}",
                f"event=foothold host={host.hostname} technique={technique_id}",
                severity="medium",
            )
        return new_state, bool(rule), alert

    if action_type == "dump_credentials":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or host.isolated or host.compromise_level == "none":
            return state, False, None
        # Harvest every credential valid on this host that isn't already
        # harvested — deterministic given the state, no extra rng draw.
        new_creds = tuple(
            (Credential(**{**asdict(c), "valid_on_host_ids": c.valid_on_host_ids, "harvested": True})
             if host_id in c.valid_on_host_ids and not c.disabled else c)
            for c in state.credentials
        )
        new_state = OrgState(
            hosts=state.hosts, segments=state.segments, credentials=new_creds,
            detection_rules=state.detection_rules, global_flags=state.global_flags,
        )
        segment = state.get_segment(host.network_segment_id)
        rule = _detect(state, technique_id, host, segment, rng)
        alert = None
        if rule:
            alert = _build_alert(
                rule, host, sequence_number,
                f"Credential dumping behavior detected on {host.hostname}",
                f"proc=lsass.exe host={host.hostname} technique={technique_id}",
                severity="high",
            )
        return new_state, bool(rule), alert

    if action_type == "escalate_privilege":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or host.isolated or host.compromise_level == "none":
            return state, False, None
        # Escalation requires a real vulnerability to exploit on the target
        # host — a host with no unpatched CVEs cannot be escalated on.
        if not host.unpatched_cves:
            return state, False, None
        next_level: CompromiseLevel = (
            "admin" if host.compromise_level == "foothold"
            else "domain_admin" if host.compromise_level == "admin"
            else host.compromise_level
        )
        if next_level == host.compromise_level:
            return state, False, None
        new_state = _replace_host(state, host_id, compromise_level=next_level)
        segment = state.get_segment(host.network_segment_id)
        rule = _detect(state, technique_id, host, segment, rng)
        alert = None
        if rule:
            alert = _build_alert(
                rule, host, sequence_number,
                f"Privilege escalation detected on {host.hostname}",
                f"host={host.hostname} new_level={next_level} technique={technique_id}",
                severity="high",
            )
        return new_state, bool(rule), alert

    if action_type == "lateral_move":
        credential_id = payload.get("credential_id")
        target_host_id = payload.get("target_host_id")
        credential = state.get_credential(credential_id)
        target_host = state.get_host(target_host_id)
        if credential is None or target_host is None:
            return state, False, None
        if target_host.isolated:
            return state, False, None
        if not (credential.harvested and not credential.disabled and target_host_id in credential.valid_on_host_ids):
            return state, False, None
        if not _segment_reachable_from_any_compromised(state, target_host.network_segment_id):
            return state, False, None

        privilege_to_level: dict[str, CompromiseLevel] = {
            "user": "foothold", "admin": "admin", "domain_admin": "domain_admin",
        }
        new_level = privilege_to_level.get(credential.privilege, "foothold")
        # Never downgrade an already-more-compromised host.
        if _COMPROMISE_ORDER[new_level] <= _COMPROMISE_ORDER[target_host.compromise_level]:
            new_level = target_host.compromise_level
        new_state = _replace_host(state, target_host_id, compromise_level=new_level)
        segment = state.get_segment(target_host.network_segment_id)
        rule = _detect(new_state, technique_id, target_host, segment, rng)
        alert = None
        if rule:
            alert = _build_alert(
                rule, target_host, sequence_number,
                f"Lateral movement detected: authentication to {target_host.hostname} using '{credential.username}'",
                f"event=4624 user={credential.username} dest={target_host.hostname} technique={technique_id}",
                severity="high",
            )
        return new_state, bool(rule), alert

    if action_type == "deploy_impact":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or host.isolated:
            return state, False, None
        # deploy_impact is the match-ending, ransomware/exfil-equivalent
        # action, so it requires real footprint, not just any compromise:
        # the target host itself must be at admin (or higher) compromise,
        # AND the attacker must have reached admin-or-higher on at least 2
        # hosts org-wide (enough footprint for the action to be plausible),
        # mirroring lateral_move's real-object-graph precondition style.
        if host.compromise_level not in ("admin", "domain_admin"):
            return state, False, None
        _MIN_HIGH_COMPROMISE_HOSTS = 2
        high_compromise_host_count = sum(
            1 for h in state.hosts if h.compromise_level in ("admin", "domain_admin")
        )
        if high_compromise_host_count < _MIN_HIGH_COMPROMISE_HOSTS:
            return state, False, None

        backups_immutable = bool(state.global_flags.get("backups_immutable"))
        new_flags = {**state.global_flags, "impact_deployed": True, "impact_host_id": host_id, "impact_contained": backups_immutable}
        new_state = OrgState(
            hosts=state.hosts, segments=state.segments, credentials=state.credentials,
            detection_rules=state.detection_rules, global_flags=new_flags,
        )
        # Impact actions are loud by design (matches redteam.py's impact
        # phase: detection_risk 0.8-1.0) — always alert (detected=True is
        # unconditional below), but the ALERT ATTRIBUTION must still be
        # honest: only borrow a real DetectionRule's identity (e.g.
        # source_system: "EDR") when that rule's conditions (requires_edr /
        # requires_monitored_segment) are actually satisfied by this
        # host/segment. Otherwise fall back to a generic, non-EDR-claiming
        # alert rather than misattributing detection to coverage that isn't
        # there.
        segment = state.get_segment(host.network_segment_id)
        rule = _detect(state, technique_id, host, segment, rng)
        if rule:
            alert = _build_alert(
                rule, host, sequence_number,
                f"Impact activity detected on {host.hostname} — encryption/exfiltration behavior",
                f"host={host.hostname} technique={technique_id} backups_immutable={backups_immutable}",
                severity="high",
            )
        else:
            alert = {
                "timestamp": f"+{sequence_number}m",
                "severity": "high",
                "source_system": "Manual Review",
                "rule_id": "IMPACT-FALLBACK",
                "description": f"Impact activity detected on {host.hostname} — encryption/exfiltration behavior",
                "raw_log": f"host={host.hostname} technique={technique_id} backups_immutable={backups_immutable}",
            }
        return new_state, True, alert

    return state, False, None


def apply_defender_action(state: OrgState, action: dict) -> OrgState:
    """Apply a defender action. Deterministic — no RNG involved. Invalid/
    unmet-precondition actions are no-ops that return `state` unchanged.
    This includes a non-dict `action` (e.g. None, a string, or a list from
    a malformed action log)."""
    if not isinstance(action, dict):
        return state

    action_type = action.get("action_type")
    payload = action.get("payload", action)

    if action_type not in DEFENDER_ACTION_TYPES:
        return state

    if action_type == "isolate_host":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or host.isolated:
            return state
        return _replace_host(state, host_id, isolated=True)

    if action_type == "disable_credential":
        credential_id = payload.get("credential_id")
        credential = state.get_credential(credential_id)
        if credential is None or credential.disabled:
            return state
        return _replace_credential(state, credential_id, disabled=True)

    if action_type == "patch_host":
        host_id = payload.get("host_id")
        host = state.get_host(host_id)
        if host is None or not host.unpatched_cves:
            return state
        cve = payload.get("cve")
        if cve:
            if cve not in host.unpatched_cves:
                return state
            remaining = tuple(c for c in host.unpatched_cves if c != cve)
        else:
            remaining = ()
        return _replace_host(state, host_id, unpatched_cves=remaining)

    if action_type == "increase_monitoring":
        segment_id = payload.get("segment_id")
        segment = state.get_segment(segment_id)
        if segment is None or segment.monitored:
            return state
        new_segments = tuple(
            (NetworkSegment(**{**asdict(s), "reachable_from": s.reachable_from, "monitored": True}) if s.id == segment_id else s)
            for s in state.segments
        )
        return OrgState(
            hosts=state.hosts, segments=new_segments, credentials=state.credentials,
            detection_rules=state.detection_rules, global_flags=state.global_flags,
        )

    if action_type == "acknowledge":
        return state

    return state


def _derive_rng(seed: int, sequence_number: int) -> random.Random:
    """Deterministically derive a per-action RNG from (seed, sequence_number).
    Same inputs always produce the same Random stream, so replaying an
    identical action log — or a truncated prefix of one, for Phase G's
    future branching replay — is byte-identical up to the point of
    divergence. Derivation goes through a SHA-256 hash of the two inputs
    (rather than raw arithmetic/XOR) specifically to avoid CPython
    `random.Random(x)` / `random.Random(-x)` producing colliding or
    mirrored streams for sign-symmetric seed pairs like (seed, -seed)."""
    h = hashlib.sha256(f"{seed}:{sequence_number}".encode()).digest()
    derived_seed = int.from_bytes(h[:8], "big")
    return random.Random(derived_seed)


def replay(seed: int, archetype_key: str, actions: list[dict]) -> tuple[OrgState, list[dict]]:
    """The single source of truth for reconstructing an ArenaMatch's state.

    Generates the initial OrgState from (seed, archetype), then folds the
    ordered `actions` list through apply_attacker_action / apply_defender_action
    (dispatched by each action's `actor` field: "attacker" | "defender",
    matching ArenaAction.actor). Returns (final_state, events) where events
    is the ordered list of emitted alerts/results — one entry per action,
    including no-op entries for defender actions and non-detected attacker
    actions, so `len(events) == len(actions)` always holds and callers can
    zip them back against the action log.

    Replaying the same (seed, archetype_key, actions) twice is byte-identical.
    Replaying a shorter prefix of `actions` reproduces the same events for
    every action up to the point of truncation/divergence.
    """
    archetype = ORG_ARCHETYPES.get(archetype_key, {})
    state = generate_org_state(seed, archetype)
    events: list[dict] = []

    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            # Malformed action log entry (None, str, int, list, ...) — skip
            # gracefully and continue processing the rest of the log rather
            # than letting one bad entry corrupt the whole match
            # reconstruction, per the module's "never raises" contract.
            events.append({
                "sequence_number": i,
                "actor": None,
                "action_type": None,
                "detected": False,
                "alert": None,
            })
            continue

        sequence_number = action.get("sequence_number", i)
        actor = action.get("actor")

        if actor == "attacker":
            rng = _derive_rng(seed, sequence_number)
            action_with_seq = {**action, "sequence_number": sequence_number}
            state, detected, alert = apply_attacker_action(state, action_with_seq, rng)
            events.append({
                "sequence_number": sequence_number,
                "actor": "attacker",
                "action_type": action.get("action_type"),
                "detected": detected,
                "alert": alert,
            })
        elif actor == "defender":
            state = apply_defender_action(state, action)
            events.append({
                "sequence_number": sequence_number,
                "actor": "defender",
                "action_type": action.get("action_type"),
                "detected": False,
                "alert": None,
            })
        else:
            # Malformed action (missing/unknown actor) — skip gracefully,
            # never raise, per the fuzz-safety requirement.
            events.append({
                "sequence_number": sequence_number,
                "actor": actor,
                "action_type": action.get("action_type"),
                "detected": False,
                "alert": None,
            })

    return state, events
