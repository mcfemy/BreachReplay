"""
Review artifact for host namespace unification (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md).

Imports app.services.host_harvest directly — the same module
action_engine.compile_scenario actually calls — so running this always
reflects exactly what production does, not a parallel reimplementation.
Reports, per flagship scenario: harvested hostnames, their assigned
segments, and the decoy hostnames generated to pad out the host budget —
i.e. the real host_plan compile_scenario would build, for eyeballing before
it ships.

Run from the backend directory: python harvest_report.py
"""
from app.services import host_harvest
from app.services.org_simulation import ORG_ARCHETYPES, _SEGMENT_NAME_POOLS
from app.services.action_engine import _archetype_key_for_scenario, _derive_rng
from seed import COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY

SCENARIOS = [COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY]

# Fixed for report reproducibility — any seed produces the same harvested
# set (harvesting doesn't depend on seed at all), but segment-fallback and
# decoy generation do, so a report needs one to be meaningful to eyeball.
REPORT_SEED = 2026


def report_scenario(scenario: dict, seed: int = REPORT_SEED) -> dict:
    archetype_key = _archetype_key_for_scenario(scenario.get("industry_vertical"))
    archetype = ORG_ARCHETYPES[archetype_key]
    host_lo, host_hi = archetype.get("host_count_range", [8, 10])
    archetype_roll = _derive_rng(seed, "archetype-host-roll").randint(int(host_lo), int(host_hi))
    valid_segments = tuple(_SEGMENT_NAME_POOLS.get(
        archetype.get("industry_vertical", "default"), _SEGMENT_NAME_POOLS["default"]
    ))

    harvested = sorted(host_harvest.harvest_hostnames(scenario))
    ioc_hostnames = host_harvest.hostnames_referenced_by_hidden_iocs(scenario)
    unresolved = ioc_hostnames - set(harvested)

    plan = host_harvest.build_host_plan(scenario, valid_segments, archetype_roll, seed)
    harvested_entries = [e for e in (plan or []) if e["is_harvested"]]
    decoy_entries = [e for e in (plan or []) if not e["is_harvested"]]

    return {
        "title": scenario["title"],
        "archetype_key": archetype_key,
        "archetype_host_budget": (host_lo, host_hi),
        "archetype_roll": archetype_roll,
        "hidden_iocs_total": len(scenario.get("hidden_iocs") or []),
        "hidden_iocs_hostname_keyed": len(ioc_hostnames),
        "unresolved_matches_on": sorted(unresolved),
        "harvested": harvested,
        "harvested_with_segments": [(e["hostname"], e["segment"]) for e in harvested_entries],
        "decoys_with_segments": [(e["hostname"], e["segment"]) for e in decoy_entries],
        "total_host_plan_size": len(plan or []),
    }


if __name__ == "__main__":
    for scenario in SCENARIOS:
        r = report_scenario(scenario)
        print(f"=== {r['title']} ===")
        print(f"  archetype: {r['archetype_key']}  budget={r['archetype_host_budget']}  roll={r['archetype_roll']}")
        print(f"  hidden_iocs total: {r['hidden_iocs_total']}  (hostname-keyed: {r['hidden_iocs_hostname_keyed']})")
        if r["unresolved_matches_on"]:
            print(f"  !! UNRESOLVED matches_on.hostname (not harvested): {r['unresolved_matches_on']}")
        print(f"  harvested hostnames ({len(r['harvested'])}): {r['harvested']}")
        print(f"  host_plan — harvested + segment ({len(r['harvested_with_segments'])}):")
        for name, seg in r["harvested_with_segments"]:
            print(f"    {name:40s} -> {seg}")
        print(f"  host_plan — decoys + segment ({len(r['decoys_with_segments'])}):")
        for name, seg in r["decoys_with_segments"]:
            print(f"    {name:40s} -> {seg}")
        print(f"  TOTAL host_plan size: {r['total_host_plan_size']}")
        print()
