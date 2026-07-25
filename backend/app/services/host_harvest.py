"""
Host namespace unification — see docs/HOST_NAMESPACE_UNIFICATION_SPEC.md.

Harvests authored hostnames from a scenario's alert_sequence/hidden_iocs
text so they can be seeded as real synthesized hosts, instead of the
network map generating its own disconnected namespace the player has no
way to deduce anything from (_build_stages's docstring already documented
this as a known limitation before this module existed).

Shared by action_engine.compile_scenario (the real compile path) and
harvest_report.py (the standalone review tool) — one implementation, so
running the report always reflects exactly what production actually does.
"""
from __future__ import annotations

import hashlib
import math
import random
import re

PADDING_RATIO = 0.2  # ~1 decoy per 5 harvested hosts — see spec for the reasoning.

# Known rule_id / ticket / CVE / directive shapes the ALL-CAPS pattern below
# can false-positive on — same WORD-WORD-NUMBER shape as a real hostname.
# A per-scenario denylist, not a structural fix; residual imprecision the
# spec calls out rather than hides.
KNOWN_NON_HOST_IDS = {
    "MS17-010", "ED-21-01", "CHG-4471", "INC-8821", "PMS-08831",
    "DEPLOY-1921", "MW-8811", "HELP-29901", "EMP-4471", "FW-OT-IT-001",
}

# Username shape: single initial + '.' + surname, optionally with trailing
# digits (d.park, j.wright, t.bourne2021) — excluded so the extractor
# doesn't confuse an authored person with an authored host.
_USERNAME_RE = re.compile(r"^[a-z]\.[a-z]+\d*$")

FILE_EXTENSIONS = (".exe", ".bin", ".txt", ".tmp", ".class", ".dll", ".b64")

HOSTNAME_PATTERNS = [
    # FQDN-style, restricted to the ".internal" suffix convention every
    # authored internal hostname in the flagship scenarios actually uses
    # (corp.internal / prod.internal / colpipe.internal) — this is what
    # structurally excludes external/vendor domains (mgmresorts.com,
    # okta.com, proton.me, barnet.nhs.uk, avsvmcloud.com) without a
    # growing denylist of external infrastructure.
    re.compile(r"\b[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)*\.internal\b"),
    # bare lowercase word-word-digits (orion-mgmt-01, app-svr-07)
    re.compile(r"\b[a-z]+-[a-z]+-\d{1,3}\b"),
    # ALL-CAPS corporate convention, 2-4 hyphenated segments, ending in
    # digits (CORP-DC-01, NHS-DOMAIN-CTRL-01, FIN-SVR-04, WKS-ONCO-04).
    # Requires 3+ total segments specifically to avoid colliding with
    # 2-segment rule_ids (EDR-045, FW-201) — known under-match on 2-segment
    # real hostnames (e.g. "DC-01"), documented in the spec rather than
    # loosened, since loosening reintroduces those collisions everywhere.
    re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+){1,3}-\d{1,3}\b"),
]

_SEGMENT_KEYWORDS_OT = ("ot", "scada", "historian", "hmi", "plc")
_SEGMENT_KEYWORDS_CLINICAL = ("pacs", "lis", "imaging", "clinical", "ward")


def _derive_rng(seed: int, salt: str) -> random.Random:
    """Same SHA-256-based derivation as action_engine._derive_rng /
    org_simulation._derive_rng — duplicated rather than imported to avoid a
    circular import (action_engine imports this module), matching this
    codebase's existing pattern of a small private per-module copy."""
    h = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _get(obj, name: str, default=None):
    """Dict-or-ORM duality, mirroring action_engine._field."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def harvest_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in HOSTNAME_PATTERNS:
        for m in pattern.findall(text):
            if m in KNOWN_NON_HOST_IDS:
                continue
            if _USERNAME_RE.match(m):
                continue
            if m.endswith(FILE_EXTENSIONS):
                continue
            found.add(m)
    # Keep only maximal matches — drops e.g. bare "corp.internal" once
    # "adfs-01.corp.internal" is also present.
    return {m for m in found if not any(m != other and m in other for other in found)}


def hostnames_referenced_by_hidden_iocs(scenario_like) -> set[str]:
    return {
        i["matches_on"]["hostname"]
        for i in (_get(scenario_like, "hidden_iocs") or [])
        if isinstance(i, dict) and isinstance(i.get("matches_on"), dict) and "hostname" in i["matches_on"]
    }


def harvest_hostnames(scenario_like) -> set[str]:
    """scenario_like: a plain dict OR an ORM Scenario instance (same
    dict-or-ORM duality action_engine.compile_scenario already accepts)."""
    alert_text = " ".join(
        f"{a.get('description','')} {a.get('raw_log','')}"
        for a in (_get(scenario_like, "alert_sequence") or [])
        if isinstance(a, dict)
    )
    ioc_text = " ".join(
        f"{i.get('description','')} {i.get('raw_log','')}"
        for i in (_get(scenario_like, "hidden_iocs") or [])
        if isinstance(i, dict)
    )
    return (
        harvest_from_text(alert_text)
        | harvest_from_text(ioc_text)
        | hostnames_referenced_by_hidden_iocs(scenario_like)
    )


def assign_segment(hostname: str, valid_segments: tuple[str, ...], seed: int) -> str:
    """Three explicit precedence tiers — see spec:
    1. Domain-suffix label (a dot-separated FQDN label matches a valid
       segment name exactly).
    2. Naming-convention keyword, restricted to segments valid for this
       scenario's archetype.
    3. Deterministic seeded fallback — reproducible per (seed, hostname),
       but distributes across segments instead of defaulting everything
       unresolved into one."""
    lower = hostname.lower()

    if "." in hostname:
        for label in lower.split("."):
            if label in valid_segments:
                return label

    if "ot" in valid_segments and any(k in lower for k in _SEGMENT_KEYWORDS_OT):
        return "ot"
    if "dmz" in valid_segments and "dmz" in lower:
        return "dmz"
    if "clinical" in valid_segments and any(k in lower for k in _SEGMENT_KEYWORDS_CLINICAL):
        return "clinical"
    if "corp" in valid_segments and "corp" in lower:
        return "corp"

    return _derive_rng(seed, f"segment-fallback:{hostname}").choice(valid_segments)


_STYLE_FQDN = "fqdn"
_STYLE_ALLCAPS = "allcaps"
_STYLE_LOWER_HYPHEN = "lower-hyphen"


def _classify_style(name: str) -> str:
    if "." in name:
        return _STYLE_FQDN
    if any(c.isupper() for c in name):
        return _STYLE_ALLCAPS
    return _STYLE_LOWER_HYPHEN


def generate_decoy_hostnames(harvested_names: list[str], count: int, seed: int) -> list[str]:
    """Same-convention decoys, derived per-scenario from the harvested
    names' own observed prefix/suffix tokens — recombined into new names
    that weren't in the original narrative, rather than a global procedural
    format. A naming-convention difference is itself a tell (spec design
    decision #3); reusing real tokens from the same scenario is what
    avoids that."""
    if count <= 0 or not harvested_names:
        return []

    rng = _derive_rng(seed, "decoy-hostnames")
    styles = [_classify_style(n) for n in harvested_names]
    dominant_style = max(set(styles), key=styles.count)
    # Restrict token pools to names that actually match the dominant style —
    # a scenario can (and does, e.g. Colonial Pipeline) mix conventions, and
    # pulling a token from an off-style name is exactly the "naming
    # convention difference is itself a tell" trap this function exists to
    # avoid (see spec design decision #3): a decoy like "vpn-WKS-12",
    # combining a lowercase prefix from one harvested name with an
    # ALL-CAPS middle token from another, is a dead giveaway.
    same_style_names = [n for n in harvested_names if _classify_style(n) == dominant_style]

    existing = set(harvested_names)
    decoys: list[str] = []
    attempts = 0
    max_attempts = count * 50  # defensive: never loop forever on a starved token pool

    if dominant_style == _STYLE_FQDN:
        suffixes = [n.split(".", 1)[1] for n in same_style_names]
        suffix = suffixes[0] if suffixes else "corp.internal"
        prefix_pool = sorted({n.split(".", 1)[0].rsplit("-", 1)[0] for n in same_style_names}) or ["host"]
        while len(decoys) < count and attempts < max_attempts:
            attempts += 1
            candidate = f"{rng.choice(prefix_pool)}-{rng.randint(1, 99):02d}.{suffix}"
            if candidate not in existing and candidate not in decoys:
                decoys.append(candidate)

    elif dominant_style == _STYLE_ALLCAPS:
        prefix_pool = sorted({n.split("-")[0] for n in same_style_names if "-" in n}) or ["HOST"]
        mid_pool = sorted({p for n in same_style_names for p in n.split("-")[1:-1]}) or ["SRV"]
        while len(decoys) < count and attempts < max_attempts:
            attempts += 1
            candidate = f"{rng.choice(prefix_pool)}-{rng.choice(mid_pool)}-{rng.randint(1, 99):02d}"
            if candidate not in existing and candidate not in decoys:
                decoys.append(candidate)

    else:
        prefix_pool = sorted({n.rsplit("-", 1)[0] for n in same_style_names if "-" in n}) or ["host"]
        while len(decoys) < count and attempts < max_attempts:
            attempts += 1
            candidate = f"{rng.choice(prefix_pool)}-{rng.randint(1, 99):02d}"
            if candidate not in existing and candidate not in decoys:
                decoys.append(candidate)

    return decoys


def build_host_plan(
    scenario_like, valid_segments: tuple[str, ...], archetype_host_count: int, seed: int,
) -> list[dict] | None:
    """Returns None when nothing was harvested — caller falls back to the
    fully-procedural path unchanged. Otherwise a list of
    {"hostname": str, "segment": str, "is_harvested": bool} covering every
    host the compiled world should contain, harvested hosts first."""
    harvested = sorted(harvest_hostnames(scenario_like))
    if not harvested:
        return None

    decoy_count = math.ceil(len(harvested) * PADDING_RATIO)
    effective_count = max(archetype_host_count, len(harvested) + decoy_count)
    decoy_count = effective_count - len(harvested)
    decoys = generate_decoy_hostnames(harvested, decoy_count, seed)

    plan = [
        {"hostname": name, "segment": assign_segment(name, valid_segments, seed), "is_harvested": True}
        for name in harvested
    ]
    plan += [
        {"hostname": name, "segment": assign_segment(name, valid_segments, seed), "is_harvested": False}
        for name in decoys
    ]
    return plan
