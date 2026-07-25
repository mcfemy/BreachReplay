"""
Unit tests for backend/app/services/host_harvest.py — host namespace
unification (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md). Pure, synchronous
tests — no I/O, no async client/db fixtures needed.
"""
from app.services import host_harvest


# ── harvest_from_text ─────────────────────────────────────────────────────

def test_harvests_internal_fqdn_and_allcaps_hostnames():
    text = "src=orion-mgmt-01.corp.internal host=CORP-DC-01 dst=vcenter-01.prod.internal"
    found = host_harvest.harvest_from_text(text)
    assert "orion-mgmt-01.corp.internal" in found
    assert "CORP-DC-01" in found
    assert "vcenter-01.prod.internal" in found


def test_excludes_external_domains_usernames_and_file_names():
    text = (
        "user=d.park@mgmresorts.com proc=vssadmin.exe "
        "dst=barnet.nhs.uk file=staged.exe rule=FW-OT-IT-001"
    )
    found = host_harvest.harvest_from_text(text)
    assert not found, f"expected nothing harvested, got {found}"


def test_drops_substring_fragments_keeping_only_maximal_matches():
    text = "src=orion-mgmt-01.corp.internal"
    found = host_harvest.harvest_from_text(text)
    assert found == {"orion-mgmt-01.corp.internal"}
    assert "corp.internal" not in found


def test_harvest_hostnames_reads_alert_sequence_and_hidden_iocs_and_matches_on():
    scenario = {
        "alert_sequence": [{"description": "x", "raw_log": "host=FIN-SVR-04"}],
        "hidden_iocs": [
            {"matches_on": {"hostname": "OT-HISTORIAN-01"}, "raw_log": "host=OT-HISTORIAN-01"},
        ],
    }
    found = host_harvest.harvest_hostnames(scenario)
    assert found == {"FIN-SVR-04", "OT-HISTORIAN-01"}


def test_harvest_hostnames_returns_empty_set_for_content_with_no_hostnames():
    assert host_harvest.harvest_hostnames({"alert_sequence": [], "hidden_iocs": []}) == set()
    assert host_harvest.harvest_hostnames({}) == set()


# ── assign_segment (3-tier precedence) ────────────────────────────────────

def test_segment_tier1_domain_suffix_label_wins_when_present():
    assert host_harvest.assign_segment("foo.dmz.internal", ("corp", "dmz", "ot"), seed=1) == "dmz"


def test_segment_tier2_keyword_convention():
    valid = ("corp", "dmz", "ot")
    assert host_harvest.assign_segment("OT-HISTORIAN-01", valid, seed=1) == "ot"
    assert host_harvest.assign_segment("scada-plc-02", valid, seed=1) == "ot"
    assert host_harvest.assign_segment("adfs-01.corp.internal", valid, seed=1) == "corp"


def test_segment_tier2_restricted_to_this_scenarios_valid_segments():
    """A "clinical" keyword must never resolve for an energy-archetype
    scenario, since "clinical" isn't a valid segment there at all."""
    valid = ("corp", "dmz", "ot")
    result = host_harvest.assign_segment("NHS-PACS-01", valid, seed=1)
    assert result in valid
    assert result != "clinical"


def test_segment_tier3_fallback_is_deterministic_and_reproducible():
    valid = ("corp", "dmz", "ot")
    a = host_harvest.assign_segment("unresolvable-host-99", valid, seed=42)
    b = host_harvest.assign_segment("unresolvable-host-99", valid, seed=42)
    assert a == b
    assert a in valid


def test_segment_tier3_fallback_distributes_not_always_corp():
    """Not a hard guarantee for any single hostname, but across many
    distinct unresolvable names the fallback must not collapse to always
    picking the same segment — that would silently reproduce the exact
    "everything defaults to corp" problem the 3-tier design avoids."""
    valid = ("corp", "dmz", "ot")
    results = {
        host_harvest.assign_segment(f"unresolvable-{i}", valid, seed=7)
        for i in range(30)
    }
    assert len(results) > 1


# ── generate_decoy_hostnames ───────────────────────────────────────────────

def test_decoys_match_allcaps_convention_and_avoid_collisions():
    harvested = ["CORP-DC-01", "FIN-SVR-04", "OT-HISTORIAN-01"]
    decoys = host_harvest.generate_decoy_hostnames(harvested, count=5, seed=1)
    assert len(decoys) == 5
    assert set(decoys).isdisjoint(harvested)
    for name in decoys:
        assert name[0].isupper()
        assert "-" in name


def test_decoys_match_fqdn_convention_with_the_scenarios_own_suffix():
    harvested = ["adfs-01.corp.internal", "orion-mgmt-01.corp.internal"]
    decoys = host_harvest.generate_decoy_hostnames(harvested, count=4, seed=1)
    assert len(decoys) == 4
    for name in decoys:
        assert name.endswith(".corp.internal")
    assert set(decoys).isdisjoint(harvested)


def test_decoy_generation_is_deterministic():
    harvested = ["CORP-DC-01", "FIN-SVR-04"]
    a = host_harvest.generate_decoy_hostnames(harvested, count=3, seed=5)
    b = host_harvest.generate_decoy_hostnames(harvested, count=3, seed=5)
    assert a == b


def test_zero_count_or_no_harvested_names_produces_no_decoys():
    assert host_harvest.generate_decoy_hostnames(["CORP-DC-01"], count=0, seed=1) == []
    assert host_harvest.generate_decoy_hostnames([], count=5, seed=1) == []


# ── build_host_plan ────────────────────────────────────────────────────────

def test_build_host_plan_returns_none_when_nothing_harvested():
    scenario = {"alert_sequence": [], "hidden_iocs": []}
    assert host_harvest.build_host_plan(scenario, ("corp", "dmz"), 10, seed=1) is None


def test_build_host_plan_places_harvested_hosts_before_decoys():
    scenario = {
        "alert_sequence": [{"description": "x", "raw_log": "host=CORP-DC-01"}],
        "hidden_iocs": [],
    }
    plan = host_harvest.build_host_plan(scenario, ("corp", "dmz"), 10, seed=1)
    assert plan is not None
    assert plan[0]["hostname"] == "CORP-DC-01"
    assert plan[0]["is_harvested"] is True
    assert all(not e["is_harvested"] for e in plan[1:])


def test_build_host_plan_respects_the_elastic_host_count_formula():
    """A scenario naming MORE hosts than the archetype's own budget must
    still seed every one of them — the whole reason host_count_range
    became scenario-aware (NHS WannaCry: 11 harvested vs an 8-10 budget)."""
    scenario = {
        "alert_sequence": [
            {"description": "x", "raw_log": f"host=srv-host-{i:02d}"} for i in range(12)
        ],
        "hidden_iocs": [],
    }
    plan = host_harvest.build_host_plan(scenario, ("corp", "dmz"), archetype_host_count=10, seed=1)
    assert plan is not None
    harvested_count = sum(1 for e in plan if e["is_harvested"])
    assert harvested_count == 12
    assert len(plan) > 10  # exceeds the archetype's own budget, as required
    assert len(plan) == 12 + max(0, __import__("math").ceil(12 * host_harvest.PADDING_RATIO))
