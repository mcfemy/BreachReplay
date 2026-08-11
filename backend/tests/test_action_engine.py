"""
Determinism tests for backend/app/services/action_engine.py (Phase 2 —
action console core loop, BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4).

Uses a scenario dict shaped like backend/seed.py's COLONIAL_PIPELINE (same
field names action_engine.compile_scenario reads) rather than importing
seed.py directly, so these tests don't depend on that script's content
staying stable. These are pure, synchronous tests — compile_scenario and
world_state_at do no I/O, so no async client/db fixtures are needed.
"""
from app.services import action_engine, verb_engine

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


def test_ioc_placements_bind_to_the_attack_path_not_any_host():
    """The reason to bind placement to the attack path at all: investigating
    a host a stage actually compromises must be able to teach you something.
    Every placed IOC's host must be one _build_stages assigned to a
    decision_gate stage — never an off-path host the attacker's own
    progression never touches, even when the world has more hosts than
    that available to place on."""
    compiled = action_engine.compile_scenario(_SCENARIO, seed=42)
    attack_path_host_ids = {hid for s in compiled.stages for hid in s.compromises_host_ids}

    assert attack_path_host_ids, "fixture must have at least one decision_gate stage for this test to mean anything"
    assert len(attack_path_host_ids) < len(compiled.world.hosts), (
        "fixture must have off-path hosts too, or binding is indistinguishable from placing on any host"
    )

    for placement in compiled.ioc_placements:
        assert placement.host_id in attack_path_host_ids


def test_ioc_placements_fall_back_to_any_host_when_there_is_no_attack_path():
    """A scenario with hidden_iocs but no decision_tree gates has no attack
    path to bind to at all — must still place IOCs (on any host) rather
    than silently dropping them or raising."""
    no_gates = dict(_SCENARIO, decision_tree=[])
    compiled = action_engine.compile_scenario(no_gates, seed=42)
    # pressure_injections still produce a stage, but pressure stages never
    # compromise a host — the attack path (compromises_host_ids across all
    # stages) is empty even though compiled.stages itself isn't.
    assert not any(s.compromises_host_ids for s in compiled.stages)

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
    # energy_utility_flagship's host_count_range [16,20] (the archetype
    # "energy" industry_vertical maps to for decision-gate content — see
    # _INDUSTRY_TO_ARCHETYPE) and small_healthcare's [8,10] are disjoint
    # (backend/app/services/org_simulation.py ORG_ARCHETYPES), so this is
    # a stable, non-flaky signal that the archetype mapping fired.
    assert 16 <= len(energy_run.world.hosts) <= 20
    assert 8 <= len(healthcare_run.world.hosts) <= 10


def test_final_stage_is_chosen_by_max_trigger_seconds_not_array_position():
    """QA fix: gates authored out of chronological order must still resolve
    is_final to the gate with the LATEST trigger_seconds, not whichever
    gate happens to be last in the array."""
    out_of_order = dict(_SCENARIO, decision_tree=[
        # +49m gate listed FIRST, +4m gate listed LAST — the opposite of
        # chronological (and opposite of array-position) order.
        {"id": "gate-012", "trigger_timestamp": "+49m", "mitre_technique": "T1565.001",
         "context_summary": "SCADA HMI going dark.", "options": [], "correct_index": 2,
         "consequence_if_wrong": "Detonation.", "rationale": "Segment shutdown.", "nist_control_ref": "RS.MI-1"},
        {"id": "gate-002", "trigger_timestamp": "+8m", "mitre_technique": "T1003",
         "context_summary": "Credential dump detected.", "options": [], "correct_index": 1,
         "consequence_if_wrong": "Missed.", "rationale": "Preserve evidence.", "nist_control_ref": "RS.AN-3"},
        {"id": "gate-001", "trigger_timestamp": "+4m", "mitre_technique": "T1078",
         "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
         "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
    ])
    compiled = action_engine.compile_scenario(out_of_order, seed=1)

    final_stages = [s for s in compiled.stages if s.is_final]
    assert len(final_stages) == 1
    assert final_stages[0].source_id == "gate-012"
    assert final_stages[0].trigger_seconds == 49 * 60
    # The stage timeline itself is still sorted by trigger_seconds regardless
    # of authored array order.
    trigger_times = [s.trigger_seconds for s in compiled.stages]
    assert trigger_times == sorted(trigger_times)


def test_ioc_raw_log_is_rewritten_to_match_the_bound_synthesized_host():
    """QA fix (superseded by host namespace unification — see
    docs/HOST_NAMESPACE_UNIFICATION_SPEC.md): revealed evidence text must
    never reference a real-world hostname/IP absent from the synthesized
    network map. Before host_harvest existed, that was enforced by
    REWRITING the authored hostname to whatever random host it landed on
    (so "CORP-DC-01" never appeared in raw_log at all). Now it's enforced
    the other way: "CORP-DC-01" is harvested into a REAL host with that
    exact hostname, so the authored name in raw_log is correct AS-IS — the
    whole point of the fix is that it's no longer a contradiction."""
    compiled = action_engine.compile_scenario(_SCENARIO, seed=42)

    hostname_ioc = _SCENARIO["hidden_iocs"][1]  # matches_on: {"hostname": "CORP-DC-01"}
    assert "hostname" in hostname_ioc["matches_on"]
    placement = compiled.ioc_placements[1]
    bound_host = compiled.world.get_host(placement.host_id)

    assert bound_host is not None
    assert bound_host.hostname == hostname_ioc["matches_on"]["hostname"]
    assert bound_host.hostname in placement.raw_log


def test_missing_compression_ratio_defaults_to_no_scaling():
    """_SCENARIO carries no compression_ratio field at all — must behave
    exactly as before this feature existed (real-world minutes used as
    literal seconds)."""
    compiled = action_engine.compile_scenario(_SCENARIO, seed=5)
    final_stage = next(s for s in compiled.stages if s.is_final)
    assert final_stage.trigger_seconds == 49 * 60


def test_compression_ratio_scales_trigger_seconds_and_stays_deterministic():
    """The actual bug fix: an 8.0 compression_ratio (the DB column's
    default) must scale every trigger_timestamp — decision gates, pressure
    injections, and alert_lines alike, since all three parse through
    _parse_trigger_seconds — and repeated compilation of the same
    (scenario, seed) must still be byte-identical, per Phase 4's ghost
    replay requirement."""
    scenario = dict(_SCENARIO, compression_ratio=8.0)
    run_a = action_engine.compile_scenario(scenario, seed=99)
    run_b = action_engine.compile_scenario(scenario, seed=99)

    assert [s.to_dict() for s in run_a.stages] == [s.to_dict() for s in run_b.stages]
    assert run_a.alert_lines == run_b.alert_lines
    assert [p.to_dict() for p in run_a.ioc_placements] == [p.to_dict() for p in run_b.ioc_placements]

    # +49m (2940s raw) / 8.0 floors to 367s, not the unscaled 2940s.
    final_stage = next(s for s in run_a.stages if s.is_final)
    assert final_stage.trigger_seconds == 2940 // 8
    assert final_stage.source_id == "gate-012"

    # Alerts scale identically, so the ambient feed never references a time
    # the compressed stage clock will never reach.
    by_timestamp = {a["timestamp"]: a["trigger_seconds"] for a in run_a.alert_lines}
    assert by_timestamp["+8m"] == 480 // 8

    # Scaling must never disturb sort order or final-stage selection.
    trigger_times = [s.trigger_seconds for s in run_a.stages]
    assert trigger_times == sorted(trigger_times)


def test_compress_seconds_floors_rather_than_rounds():
    """250s / 7.0 = 35.71...; floor is 35, round-to-nearest would be 36 —
    asserting the exact value pins down which policy is in effect."""
    assert action_engine._compress_seconds(250, 7.0) == 35


def test_compress_seconds_falls_back_to_no_scaling_for_invalid_ratio():
    """A missing/zero/negative authored compression_ratio must never raise
    (ZeroDivisionError) or silently produce a nonsensical negative/inflated
    trigger_seconds — falls back to ratio 1.0 (no compression), matching
    every other "bad authored content never crashes compilation" guard in
    this module."""
    assert action_engine._compress_seconds(120, 0) == 120
    assert action_engine._compress_seconds(120, -5) == 120
    assert action_engine._compress_seconds(120, None) == 120


def test_breach_head_start_pre_fires_several_hosts_and_stays_deterministic():
    """The 'incident already in progress' fix: world_state_at(compiled, 0)
    — and therefore the player's very first scan_network — must already
    show multiple compromised hosts, not a pristine map, and repeated
    compilation of the same (scenario, seed) must still be byte-identical."""
    scenario = dict(_SCENARIO, compression_ratio=8.0)
    run_a = action_engine.compile_scenario(scenario, seed=7)
    run_b = action_engine.compile_scenario(scenario, seed=7)

    assert run_a.world.to_dict() == run_b.world.to_dict()
    assert run_a.breach_head_start_seconds == run_b.breach_head_start_seconds

    compromised_at_zero = [
        h for h in action_engine.world_state_at(run_a, 0).hosts if h.compromise_level != "none"
    ]
    assert len(compromised_at_zero) >= 2

    # The final (terminal) stage must never be pre-fired at compile time —
    # the player always has an active, not-yet-lost run to walk into.
    final_stage = next(s for s in run_a.stages if s.is_final)
    assert run_a.breach_head_start_seconds < final_stage.trigger_seconds


def test_breach_head_start_never_reaches_the_final_stage_of_a_short_scenario():
    """A scenario whose final stage's compressed trigger_seconds falls at
    or below BREACH_HEAD_START_SECONDS must clamp the effective head start
    below it, not pre-fire the loss/terminal condition before the player
    has taken a single action."""
    short_scenario = dict(
        _SCENARIO,
        compression_ratio=100.0,  # 49m (2940s) / 100 = 29s final trigger
    )
    compiled = action_engine.compile_scenario(short_scenario, seed=3)
    final_stage = next(s for s in compiled.stages if s.is_final)

    assert final_stage.trigger_seconds <= action_engine.BREACH_HEAD_START_SECONDS
    assert compiled.breach_head_start_seconds < final_stage.trigger_seconds

    state_at_zero = action_engine.world_state_at(compiled, 0)
    final_targets = [state_at_zero.get_host(hid) for hid in final_stage.compromises_host_ids]
    assert all(h is not None and h.compromise_level == "none" for h in final_targets)


def test_new_run_world_matches_world_state_at_zero_and_advances_without_double_firing():
    """verb_engine.new_run must start from the exact same pre-fired world
    action_engine.world_state_at(compiled, 0) produces (not a pristine
    one), and its attacker_clock_offset must be seeded so a live run's
    apply_verb never re-applies a stage already folded into that baseline."""
    scenario = dict(_SCENARIO, compression_ratio=8.0)
    compiled = action_engine.compile_scenario(scenario, seed=7)

    run = verb_engine.new_run(compiled)
    assert run.world.to_dict() == action_engine.world_state_at(compiled, 0).to_dict()
    assert verb_engine.attacker_clock_seconds(run) == compiled.breach_head_start_seconds

    # A cheap verb (block_ip, cost 15s, deliberately wrong target so it's a
    # pure clock-advance with no world mutation of its own) must not
    # double-advance any host the head start already compromised.
    result = verb_engine.apply_verb(run, "block_ip", target="no-such-ip")
    pre_fired_ids = {hid for s in compiled.stages if s.trigger_seconds <= compiled.breach_head_start_seconds for hid in s.compromises_host_ids}
    for hid in pre_fired_ids:
        before = run.world.get_host(hid)
        after = result.run.world.get_host(hid)
        assert before.compromise_level == after.compromise_level


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


# ── Host namespace unification (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md) ─────

_HOST_UNIFICATION_SCENARIO = {
    "id": "test-scenario-host-unification",
    "industry_vertical": "energy",
    "alert_sequence": [
        {"timestamp": "+0m", "severity": "medium", "source_system": "VPN Gateway", "rule_id": "VPN-001",
         "description": "Suspicious login on the finance server", "raw_log": "auth=success host=FIN-SVR-04"},
        {"timestamp": "+5m", "severity": "high", "source_system": "EDR", "rule_id": "EDR-045",
         "description": "Process anomaly on the OT historian", "raw_log": "proc=lsass.exe host=OT-HISTORIAN-01"},
    ],
    "decision_tree": [
        {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
         "context_summary": "Suspicious activity.", "options": [], "correct_index": 0,
         "consequence_if_wrong": "Missed.", "rationale": "Correlate.", "nist_control_ref": "DE.AE-2"},
        {"id": "gate-002", "trigger_timestamp": "+6m", "mitre_technique": "T1003",
         "context_summary": "Anomaly detected.", "options": [], "correct_index": 1,
         "consequence_if_wrong": "Missed.", "rationale": "Preserve evidence.", "nist_control_ref": "RS.AN-3"},
    ],
    "pressure_injections": [],
    "hidden_iocs": [
        {"matches_on": {"hostname": "FIN-SVR-04"}, "timestamp": "+1m", "severity": "high",
         "source_system": "EDR", "rule_id": "EVIDENCE-01", "description": "Evidence on the finance server",
         "raw_log": "proc=certutil.exe host=FIN-SVR-04"},
        {"matches_on": {"hostname": "OT-HISTORIAN-01"}, "timestamp": "+4m", "severity": "critical",
         "source_system": "Sysmon", "rule_id": "EVIDENCE-02", "description": "Evidence on the OT historian",
         "raw_log": "proc=vssadmin.exe host=OT-HISTORIAN-01"},
        {"matches_on": {"ip": "185.220.101.34"}, "timestamp": "+3m", "severity": "medium",
         "source_system": "Auth", "rule_id": "EVIDENCE-03", "description": "IP-keyed evidence, no hostname",
         "raw_log": "src_ip=185.220.101.34"},
    ],
}


def test_every_alert_sequence_hostname_resolves_to_a_real_map_host():
    """The core promise of the fix: a hostname a player reads in the alert
    feed must exist as an actual, clickable host on the map — not a
    disconnected namespace."""
    compiled = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=17)
    map_hostnames = {h.hostname for h in compiled.world.hosts}
    assert "FIN-SVR-04" in map_hostnames
    assert "OT-HISTORIAN-01" in map_hostnames


def test_every_hidden_ioc_hostname_resolves_to_its_exact_named_host():
    """A hostname-keyed hidden_ioc must bind to the REAL host with that
    exact name — not a random host that merely happens to be on the attack
    path (the pre-fix behavior). This is what makes "read the alert, find
    the host, query it" work: querying the named host must reveal THIS
    specific evidence, deterministically."""
    compiled = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=17)
    hostname_to_id = {h.hostname: h.id for h in compiled.world.hosts}

    fin_placement = next(p for p in compiled.ioc_placements if p.rule_id == "EVIDENCE-01")
    ot_placement = next(p for p in compiled.ioc_placements if p.rule_id == "EVIDENCE-02")
    assert fin_placement.host_id == hostname_to_id["FIN-SVR-04"]
    assert ot_placement.host_id == hostname_to_id["OT-HISTORIAN-01"]

    # Both named hosts must actually be on the attack path — the point of
    # `preferred_host_ids` — so investigating a visibly compromised host
    # can always teach the player something (not violated by the exact
    # binding above).
    attack_path_host_ids = {hid for s in compiled.stages for hid in s.compromises_host_ids}
    assert hostname_to_id["FIN-SVR-04"] in attack_path_host_ids
    assert hostname_to_id["OT-HISTORIAN-01"] in attack_path_host_ids

    # The ip-keyed IOC is unaffected by any of this — still placed on an
    # attack-path host via the pre-existing random-choice fallback (the
    # verb-coverage gap for non-hostname matches_on types is a separate,
    # explicitly out-of-scope backlog item, not something this fix touches).
    ip_placement = next(p for p in compiled.ioc_placements if p.rule_id == "EVIDENCE-03")
    assert ip_placement.host_id in attack_path_host_ids


def test_host_namespace_unification_stays_deterministic():
    """Same (scenario, seed) must still compile byte-identical, including
    the new harvested-host/decoy machinery — Phase 4 ghost racing depends
    on this exactly as much as it did before host_harvest existed."""
    run_a = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=99)
    run_b = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=99)
    assert run_a.world.to_dict() == run_b.world.to_dict()
    assert [p.to_dict() for p in run_a.ioc_placements] == [p.to_dict() for p in run_b.ioc_placements]
    assert [s.to_dict() for s in run_a.stages] == [s.to_dict() for s in run_b.stages]

    run_c = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=100)
    assert run_a.world.to_dict() != run_c.world.to_dict()


def test_harvested_hosts_never_leak_matches_on_or_unfired_stage_data():
    """Leak-safety criterion (b) from the spec, re-verified against the new
    compile path: matches_on and mitre_technique must never appear in what
    a client-facing IOCPlacement.to_dict() would actually send."""
    compiled = action_engine.compile_scenario(_HOST_UNIFICATION_SCENARIO, seed=17)
    for placement in compiled.ioc_placements:
        d = placement.to_dict()
        assert "matches_on" not in d
        assert "mitre_technique" not in d
        # The authored matching hint's raw value must never appear verbatim
        # in what gets sent either (only the rewritten raw_log does).
        assert set(d.keys()) == {"host_id", "description", "severity", "source_system", "rule_id", "raw_log"}
