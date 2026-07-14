"""
Determinism tests for backend/app/services/action_engine.py (Phase 2 —
action console core loop, BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4).

Uses a scenario dict shaped like backend/seed.py's COLONIAL_PIPELINE (same
field names action_engine.compile_scenario reads) rather than importing
seed.py directly, so these tests don't depend on that script's content
staying stable. These are pure, synchronous tests — compile_scenario and
world_state_at do no I/O, so no async client/db fixtures are needed.
"""
from app.services import action_engine

_SCENARIO = {
    "id": "test-scenario-colonial",
    "industry_vertical": "energy",
    "alert_sequence": [
        {"timestamp": "+0m", "severity": "medium", "source_system": "VPN Gateway", "rule_id": "VPN-001",
         "description": "Successful VPN login from unusual geolocation", "raw_log": "auth=success"},
        {"timestamp": "+8m", "severity": "high", "source_system": "EDR", "rule_id": "EDR-045",
         "description": "Mimikatz-like credential dumping detected", "raw_log": "proc=lsass.exe"},
    ],
    "decision_tree": [
        {"id": "gate-001", "trigger_timestamp": "+4m", "mitre_technique": "T1078",
         "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
         "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
        {"id": "gate-002", "trigger_timestamp": "+8m", "mitre_technique": "T1003",
         "context_summary": "Credential dump detected.", "options": [], "correct_index": 1,
         "consequence_if_wrong": "Missed.", "rationale": "Preserve evidence.", "nist_control_ref": "RS.AN-3"},
        {"id": "gate-012", "trigger_timestamp": "+49m", "mitre_technique": "T1565.001",
         "context_summary": "SCADA HMI going dark.", "options": [], "correct_index": 2,
         "consequence_if_wrong": "Detonation.", "rationale": "Segment shutdown.", "nist_control_ref": "RS.MI-1"},
    ],
    "pressure_injections": [
        {"id": "pressure-001", "trigger_timestamp": "+3m", "type": "email",
         "from": "Shift Lead", "subject": "Status?", "body": "Need a status line."},
    ],
    "hidden_iocs": [
        {"matches_on": {"ip": "185.220.101.34"}, "timestamp": "+1m", "severity": "medium",
         "source_system": "Auth", "rule_id": "AUTH-009", "description": "Same-IP login on legacy portal",
         "raw_log": "auth=success src_ip=185.220.101.34"},
        {"matches_on": {"hostname": "CORP-DC-01"}, "timestamp": "+7m", "severity": "medium",
         "source_system": "EDR", "rule_id": "EDR-030", "description": "LOLBin activity before credential dump",
         "raw_log": "proc=certutil.exe host=CORP-DC-01"},
    ],
}


def test_same_scenario_and_seed_produce_a_byte_identical_compiled_run():
    run_a = action_engine.compile_scenario(_SCENARIO, seed=12345)
    run_b = action_engine.compile_scenario(_SCENARIO, seed=12345)

    assert run_a.world.to_dict() == run_b.world.to_dict()
    assert [s.to_dict() for s in run_a.stages] == [s.to_dict() for s in run_b.stages]
    assert [e.to_dict() for e in run_a.edges] == [e.to_dict() for e in run_b.edges]
    assert [p.to_dict() for p in run_a.ioc_placements] == [p.to_dict() for p in run_b.ioc_placements]
    assert run_a.alert_lines == run_b.alert_lines
    assert run_a.final_stage_id == run_b.final_stage_id


def test_different_seed_produces_a_different_world():
    run_a = action_engine.compile_scenario(_SCENARIO, seed=111)
    run_b = action_engine.compile_scenario(_SCENARIO, seed=222)
    assert run_a.world.to_dict() != run_b.world.to_dict()


def test_stage_timeline_is_sorted_and_final_stage_is_the_last_authored_gate():
    compiled = action_engine.compile_scenario(_SCENARIO, seed=1)

    trigger_times = [s.trigger_seconds for s in compiled.stages]
    assert trigger_times == sorted(trigger_times)

    final_stages = [s for s in compiled.stages if s.is_final]
    assert len(final_stages) == 1
    assert final_stages[0].source_id == "gate-012"
    assert final_stages[0].trigger_seconds == 49 * 60
    assert compiled.final_stage_id == final_stages[0].id

    # Pressure injections never carry a host compromise.
    pressure_stages = [s for s in compiled.stages if s.kind == "pressure"]
    assert len(pressure_stages) == 1
    assert pressure_stages[0].compromises_host_ids == ()


def test_world_state_at_zero_seconds_is_fully_uncompromised():
    compiled = action_engine.compile_scenario(_SCENARIO, seed=7)
    state = action_engine.world_state_at(compiled, 0)
    assert all(h.compromise_level == "none" for h in state.hosts)


def test_world_state_at_progresses_deterministically_with_elapsed_time():
    compiled = action_engine.compile_scenario(_SCENARIO, seed=7)

    early = action_engine.world_state_at(compiled, 5 * 60)   # only gate-001 (+4m) has fired
    late = action_engine.world_state_at(compiled, 60 * 60)   # every gate, including the +49m final, has fired

    early_compromised = sum(1 for h in early.hosts if h.compromise_level != "none")
    late_compromised = sum(1 for h in late.hosts if h.compromise_level != "none")
    assert early_compromised == 1
    assert late_compromised > 0
    assert late_compromised >= early_compromised

    # Determinism: recomputing at the same elapsed time gives a byte-identical state.
    late_again = action_engine.world_state_at(compiled, 60 * 60)
    assert late.to_dict() == late_again.to_dict()


def test_ioc_placements_bind_to_real_synthesized_hosts():
    compiled = action_engine.compile_scenario(_SCENARIO, seed=42)
    host_ids = {h.id for h in compiled.world.hosts}
    assert len(compiled.ioc_placements) == len(_SCENARIO["hidden_iocs"])
    for placement in compiled.ioc_placements:
        assert placement.host_id in host_ids


def test_alert_lines_carry_parsed_trigger_seconds():
    compiled = action_engine.compile_scenario(_SCENARIO, seed=3)
    by_timestamp = {a["timestamp"]: a["trigger_seconds"] for a in compiled.alert_lines}
    assert by_timestamp["+0m"] == 0
    assert by_timestamp["+8m"] == 480


def test_industry_vertical_selects_the_matching_archetype():
    energy_run = action_engine.compile_scenario(_SCENARIO, seed=1)
    healthcare_run = action_engine.compile_scenario(
        dict(_SCENARIO, industry_vertical="healthcare", id="test-healthcare"), seed=1
    )
    # energy_utility's host_count_range [12,15] and small_healthcare's [8,10]
    # are disjoint (backend/app/services/org_simulation.py ORG_ARCHETYPES),
    # so this is a stable, non-flaky signal that the archetype mapping fired.
    assert 12 <= len(energy_run.world.hosts) <= 15
    assert 8 <= len(healthcare_run.world.hosts) <= 10


def test_compile_scenario_accepts_a_missing_or_empty_content_gracefully():
    """A scenario with no decision_tree/pressure_injections/hidden_iocs/
    alert_sequence at all must not raise — mirrors org_simulation.py's
    "never raises on malformed/missing content" contract."""
    compiled = action_engine.compile_scenario({"id": "bare", "industry_vertical": "energy"}, seed=1)
    assert compiled.stages == ()
    assert compiled.ioc_placements == ()
    assert compiled.alert_lines == ()
    assert compiled.final_stage_id is None
    assert len(compiled.world.hosts) > 0
