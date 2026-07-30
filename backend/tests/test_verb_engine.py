"""
Tests for backend/app/services/verb_engine.py (Phase 2, Item 1 — verb
application layer). Pure, synchronous tests — apply_verb does no I/O.
"""
import json
import re

import pytest

from app.services import action_engine, verb_engine

_SCENARIO = {
    "id": "test-scenario-colonial",
    "industry_vertical": "energy",
    "alert_sequence": [
        {"timestamp": "+0m", "severity": "medium", "source_system": "VPN Gateway", "rule_id": "VPN-001",
         "description": "Successful VPN login from unusual geolocation", "raw_log": "auth=success"},
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
        {"matches_on": {"username": "svc_backup"}, "timestamp": "+31m", "severity": "high",
         "source_system": "IAM", "rule_id": "IAM-018", "description": "svc_backup added to privileged group",
         "raw_log": "event=4728 member=svc_backup"},
    ],
}


def _compiled(seed=7):
    return action_engine.compile_scenario(_SCENARIO, seed=seed)


def _run_clock_past(run, target_clock_seconds):
    """Test helper: spend scan_network calls (free of side effects on any
    specific host) until the attacker clock has passed target_clock_seconds."""
    while verb_engine.attacker_clock_seconds(run) <= target_clock_seconds:
        run = verb_engine.apply_verb(run, "scan_network").run
    return run


def test_every_verb_advances_elapsed_seconds_by_its_exact_spec_cost():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    host_id = compiled.world.hosts[0].id
    cred = compiled.world.credentials[0]

    expected_costs = {
        "query_logs": (30, host_id),
        "scan_network": (45, None),
        "isolate": (20, compiled.world.hosts[1].id),
        "image_disk": (90, compiled.world.hosts[2].id),
        "interview_user": (60, compiled.world.hosts[3 % len(compiled.world.hosts)].id),
        "block_ip": (15, "10.0.0.1"),  # deliberately wrong — cost still applies
        "reset_creds": (40, cred.username),
        "escalate": (0, None),
    }
    assert expected_costs.keys() == verb_engine.VERB_COSTS.keys()

    elapsed = 0
    for verb, (cost, target) in expected_costs.items():
        result = verb_engine.apply_verb(run, verb, target)
        assert result.error is None, f"{verb} failed: {result.error}"
        elapsed += cost
        assert result.run.elapsed_seconds == elapsed, f"{verb} did not advance the clock by {cost}s"
        run = result.run


def test_isolate_prevents_a_stage_compromise():
    compiled = _compiled()
    first_stage = next(s for s in compiled.stages if s.compromises_host_ids)
    target_host_id = first_stage.compromises_host_ids[0]
    # Enough clock time (in verb costs) to cross first_stage.trigger_seconds
    # (+4m = 240s) several times over, so if isolation didn't work the host
    # would clearly show compromise.
    padding_verbs = [("query_logs", target_host_id)] * 10  # 10 * 30s = 300s > 240s

    # Baseline: no isolation — the host DOES get compromised once enough
    # clock time has passed.
    baseline_run = verb_engine.new_run(compiled)
    for verb, target in padding_verbs:
        baseline_run = verb_engine.apply_verb(baseline_run, verb, target).run
    baseline_host = baseline_run.world.get_host(target_host_id)
    assert baseline_host.compromise_level != "none"

    # Isolate the target FIRST, before spending any time — then spend the
    # same amount of clock time. The host must stay uncompromised.
    isolated_run = verb_engine.new_run(compiled)
    isolated_run = verb_engine.apply_verb(isolated_run, "isolate", target_host_id).run
    assert isolated_run.world.get_host(target_host_id).isolated is True
    for verb, target in padding_verbs:
        isolated_run = verb_engine.apply_verb(isolated_run, verb, target).run
    isolated_host = isolated_run.world.get_host(target_host_id)
    assert isolated_host.compromise_level == "none"
    assert isolated_host.isolated is True


def test_wrong_isolation_records_a_precision_penalty():
    compiled = _compiled()
    attack_path = verb_engine._attack_path_host_ids(compiled)
    off_path_host = next(h for h in compiled.world.hosts if h.id not in attack_path)

    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "isolate", off_path_host.id)
    assert result.delta["on_attack_path"] is False
    assert any(p["type"] == "wrong_isolation" for p in result.run.penalties)


def test_correct_isolation_records_no_precision_penalty():
    compiled = _compiled()
    on_path_host_id = next(iter(verb_engine._attack_path_host_ids(compiled)))

    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "isolate", on_path_host_id)
    assert result.delta["on_attack_path"] is True
    assert not any(p["type"] == "wrong_isolation" for p in result.run.penalties)


def test_escalate_is_rejected_on_second_use():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)

    first = verb_engine.apply_verb(run, "escalate")
    assert first.error is None
    assert first.run.escalate_used is True
    assert first.run.attacker_clock_offset == verb_engine.ESCALATE_FREEZE_SECONDS
    assert first.run.elapsed_seconds == 0  # escalate costs 0s

    second = verb_engine.apply_verb(first.run, "escalate")
    assert second.error == "escalate already used this run"
    # Rejected call must leave the run completely unchanged.
    assert second.run == first.run
    assert second.run.attacker_clock_offset == verb_engine.ESCALATE_FREEZE_SECONDS


def test_escalate_freezes_the_attacker_clock_by_a_permanent_60s_offset():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    run = verb_engine.apply_verb(run, "escalate").run
    assert verb_engine.attacker_clock_seconds(run) == 0

    # 40s of real elapsed time later, the attacker clock is still behind by
    # the frozen 60s (max(0, 40 - 60) == 0, not 40).
    run = verb_engine.apply_verb(run, "block_ip", "no-match").run  # 15s
    run = verb_engine.apply_verb(run, "isolate", compiled.world.hosts[0].id).run  # 20s
    assert run.elapsed_seconds == 35
    assert verb_engine.attacker_clock_seconds(run) == 0  # max(0, 35 - 60)


def test_query_logs_reveals_only_iocs_bound_to_that_host():
    compiled = _compiled()
    target_placement = compiled.ioc_placements[0]
    run = verb_engine.new_run(compiled)

    result = verb_engine.apply_verb(run, "query_logs", target_placement.host_id)
    revealed_rule_ids = {ioc["rule_id"] for ioc in result.delta["revealed_iocs"]}
    assert target_placement.rule_id in revealed_rule_ids

    other_placements_same_host = [
        p for p in compiled.ioc_placements if p.host_id == target_placement.host_id
    ]
    assert len(result.delta["revealed_iocs"]) == len(other_placements_same_host)

    # Querying the SAME host again reveals nothing new (already discovered).
    result2 = verb_engine.apply_verb(result.run, "query_logs", target_placement.host_id)
    assert result2.delta["revealed_iocs"] == []


def test_block_ip_correct_isolates_the_bound_host():
    compiled = _compiled()
    ip_ioc = next(p for p in compiled.ioc_placements if p.matches_on.get("ip"))
    run = verb_engine.new_run(compiled)

    result = verb_engine.apply_verb(run, "block_ip", ip_ioc.matches_on["ip"])
    assert result.delta["correct"] is True
    assert result.delta["host_id"] == ip_ioc.host_id
    assert result.run.world.get_host(ip_ioc.host_id).isolated is True


def test_block_ip_answer_is_discoverable_through_legitimate_play():
    """Closes the loop end to end: the address block_ip expects must be
    reachable by actually playing (query_logs -> read the revealed raw_log
    -> extract the IP -> block_ip), not just known server-side via
    IOCPlacement.matches_on, which no real player can ever see. A prior
    version of _rewrite_raw_log_for_host replaced the IP token in raw_log
    with the bound host's hostname, which erased the answer from every
    surface a player can observe — this test is the regression guard for
    that bug."""
    compiled = _compiled()
    ip_placement = next(p for p in compiled.ioc_placements if p.matches_on.get("ip"))
    run = verb_engine.new_run(compiled)

    reveal = verb_engine.apply_verb(run, "query_logs", ip_placement.host_id)
    revealed = next(ioc for ioc in reveal.delta["revealed_iocs"] if ioc["rule_id"] == ip_placement.rule_id)

    match = re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", revealed["raw_log"])
    assert match is not None, "the IP must be discoverable in the revealed raw_log text"
    extracted_ip = match.group(0)

    result = verb_engine.apply_verb(reveal.run, "block_ip", extracted_ip)
    # revealed_iocs included for live/resync parity (see
    # test_action_run_ws_handler.py's
    # test_block_ip_correct_guess_includes_the_matched_ioc_body_live_and_on_resync)
    # — discovered_ioc_keys already counts this as earned the instant the
    # correct IP is blocked, so the live delta must show what a resync
    # would show, not under-report it. tool_output (diegetic iptables
    # rendering) checked separately below, not part of this dict-equality
    # assertion — it's covered on its own in test_tool_output.py.
    delta = dict(result.delta)
    tool_output = delta.pop("tool_output")
    assert delta == {
        "correct": True,
        "host_id": ip_placement.host_id,
        "revealed_iocs": [ip_placement.to_dict()],
    }
    assert extracted_ip in tool_output["command"]


def test_block_ip_wrong_address_records_a_penalty_and_isolates_nothing():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "block_ip", "9.9.9.9")
    assert result.delta["correct"] is False
    assert set(result.delta.keys()) == {"correct", "tool_output"}
    assert any(p["type"] == "wrong_block_ip" for p in result.run.penalties)
    assert not any(h.isolated for h in result.run.world.hosts)


def test_reset_creds_correct_disables_the_credential():
    compiled = _compiled()
    cred = compiled.world.credentials[0]
    run = verb_engine.new_run(compiled)

    result = verb_engine.apply_verb(run, "reset_creds", cred.username)
    assert result.delta["correct"] is True
    updated = result.run.world.get_credential(cred.id)
    assert updated.disabled is True


def test_reset_creds_unknown_account_records_a_penalty():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "reset_creds", "not-a-real-account")
    assert result.delta["correct"] is False
    assert set(result.delta.keys()) == {"correct", "tool_output"}


def test_reset_creds_wrong_guess_penalty_matches_block_ip_exactly():
    """Containment verbs double as value-pivots (docs/HOST_NAMESPACE_UNIFICATION_SPEC.md)
    — a wrong username guess must cost exactly what a wrong IP guess costs,
    or brute-forcing input is cheaper than reading the alert feed and the
    deduction premise collapses. Locks the two penalty amounts together
    explicitly so they can't silently drift apart."""
    compiled = _compiled()
    run = verb_engine.new_run(compiled)

    creds_result = verb_engine.apply_verb(run, "reset_creds", "not-a-real-account")
    ip_result = verb_engine.apply_verb(run, "block_ip", "9.9.9.9")

    creds_penalty = next(p for p in creds_result.run.penalties if p["type"] == "wrong_reset_creds")
    ip_penalty = next(p for p in ip_result.run.penalties if p["type"] == "wrong_block_ip")
    assert creds_penalty["amount"] == ip_penalty["amount"] == verb_engine.PRECISION_PENALTY


def test_reset_creds_reveals_a_username_keyed_ioc_by_value_alongside_the_credential():
    """_SCENARIO's username-keyed IOC ("svc_backup") happens to also be a
    real procedurally-generated Credential.username for this archetype/seed
    — deliberately exercises the "both match simultaneously" case: the
    credential still gets disabled (existing containment behavior,
    unaffected) AND the IOC is revealed by value in the same call."""
    compiled = _compiled()
    username_ioc = next(p for p in compiled.ioc_placements if p.matches_on.get("username"))
    cred = next(c for c in compiled.world.credentials if c.username == username_ioc.matches_on["username"])
    run = verb_engine.new_run(compiled)

    result = verb_engine.apply_verb(run, "reset_creds", username_ioc.matches_on["username"])
    assert result.delta["correct"] is True
    assert result.delta["credential_id"] == cred.id
    assert result.delta["revealed_iocs"] == [username_ioc.to_dict()]
    assert result.run.world.get_credential(cred.id).disabled is True


def test_reset_creds_reveals_a_username_keyed_ioc_with_no_matching_credential():
    """Mirrors real content (MGM's CROSSTENANT IOC: matches_on.username =
    "d.park@mgmresorts.com", which is never a procedurally-generated
    Credential.username — a different namespace entirely). Submitting it
    must still count as correct and reveal the IOC, with no credential_id
    in the delta since nothing was actually disabled."""
    scenario = dict(_SCENARIO, hidden_iocs=[
        {"matches_on": {"username": "d.park@mgmresorts.com"}, "timestamp": "+5m", "severity": "critical",
         "source_system": "Okta", "rule_id": "MGM-CROSSTENANT-01", "description": "Cross-tenant impersonation",
         "raw_log": "actor=d.park@mgmresorts.com outcome=SUCCESS"},
    ])
    compiled = action_engine.compile_scenario(scenario, seed=7)
    ioc = compiled.ioc_placements[0]
    assert not any(c.username == "d.park@mgmresorts.com" for c in compiled.world.credentials)
    run = verb_engine.new_run(compiled)

    result = verb_engine.apply_verb(run, "reset_creds", "d.park@mgmresorts.com")
    delta = dict(result.delta)
    delta.pop("tool_output")
    assert delta == {"correct": True, "revealed_iocs": [ioc.to_dict()]}


def test_reset_creds_username_answer_is_discoverable_through_legitimate_play():
    """Closes the loop end to end, mirroring
    test_block_ip_answer_is_discoverable_through_legitimate_play: the
    username reset_creds expects must be reachable by actually playing
    (query_logs -> read the revealed raw_log -> extract the username ->
    reset_creds), not just known server-side via IOCPlacement.matches_on."""
    compiled = _compiled()
    username_ioc = next(p for p in compiled.ioc_placements if p.matches_on.get("username"))
    run = verb_engine.new_run(compiled)

    reveal = verb_engine.apply_verb(run, "query_logs", username_ioc.host_id)
    revealed = next(ioc for ioc in reveal.delta["revealed_iocs"] if ioc["rule_id"] == username_ioc.rule_id)

    assert username_ioc.matches_on["username"] in revealed["raw_log"], (
        "the username must be discoverable in the revealed raw_log text"
    )

    result = verb_engine.apply_verb(reveal.run, "reset_creds", username_ioc.matches_on["username"])
    assert result.delta["correct"] is True
    assert result.delta["revealed_iocs"] == [username_ioc.to_dict()]


def test_unknown_verb_and_missing_target_are_rejected_without_spending_clock():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)

    bad_verb = verb_engine.apply_verb(run, "hack_the_mainframe", "host-1")
    assert bad_verb.error is not None
    assert bad_verb.run.elapsed_seconds == 0

    missing_target = verb_engine.apply_verb(run, "isolate", None)
    assert missing_target.error is not None
    assert missing_target.run.elapsed_seconds == 0

    unknown_host = verb_engine.apply_verb(run, "isolate", "not-a-real-host")
    assert unknown_host.error is not None
    assert unknown_host.run.elapsed_seconds == 0


def test_action_log_records_every_applied_verb_in_order():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    host_id = compiled.world.hosts[0].id

    run = verb_engine.apply_verb(run, "scan_network").run
    run = verb_engine.apply_verb(run, "query_logs", host_id).run
    # A rejected call must NOT appear in the log.
    verb_engine.apply_verb(run, "isolate", None)

    assert [entry["verb"] for entry in run.action_log] == ["scan_network", "query_logs"]
    assert [entry["sequence_number"] for entry in run.action_log] == [0, 1]
    assert run.action_log[0]["elapsed_seconds"] == 45
    assert run.action_log[1]["elapsed_seconds"] == 75


def test_no_verb_response_ever_leaks_unrevealed_hidden_state():
    """Anti-leak test, mirroring backend/tests/test_teaser.py's pattern:
    plays a realistic sequence of verbs and asserts that at no point does a
    delta contain another host's hidden IOC text, the raw stage timeline,
    or any hidden_iocs the player hasn't earned yet.

    This also covers diegetic tool_output (backend/app/services/
    tool_output.py) for free, without any changes needed here: tool_output
    is nested INSIDE each verb's own delta (verb_engine.apply_verb), so
    `payload = json.dumps(result.delta)` below already serializes it, and
    the raw_log/description containment checks scan the whole payload
    string — an unrevealed IOC's text leaking through render_query_logs or
    render_image_disk specifically would already fail this test exactly
    like a leak anywhere else in the delta would."""
    compiled = _compiled(seed=99)
    run = verb_engine.new_run(compiled)

    host_a, host_b = compiled.world.hosts[0].id, compiled.world.hosts[1].id
    sequence = [
        ("scan_network", None),
        ("query_logs", host_a),
        ("interview_user", host_a),
        ("image_disk", host_b),
        ("block_ip", "not-a-real-ip"),
        ("reset_creds", "not-a-real-account"),
        ("escalate", None),
    ]

    all_ioc_text = [p.description for p in compiled.ioc_placements] + [p.raw_log for p in compiled.ioc_placements]
    forbidden_keys = {"stages", "trigger_seconds", "mitre_technique", "hidden_iocs", "ioc_placements", "matches_on"}

    for verb, target in sequence:
        result = verb_engine.apply_verb(run, verb, target)
        run = result.run
        payload = json.dumps(result.delta)

        # No forbidden structural keys anywhere in the delta.
        assert not (forbidden_keys & set(json.loads(payload).keys())), f"{verb} delta leaked a forbidden top-level key"

        # No undiscovered IOC's text ever appears, except for the host(s)
        # actually targeted in THIS call (query_logs/image_disk legitimately
        # reveal their own host's IOC text).
        for placement in compiled.ioc_placements:
            if placement.host_id in (host_a, host_b) and verb in ("query_logs", "image_disk"):
                continue  # legitimately earned this call
            assert placement.description not in payload
            assert placement.raw_log not in payload

    # Final sanity: only host_a/host_b's IOCs were ever discovered — nothing
    # bound to any other host was revealed across the whole sequence.
    for host_id, rule_id in run.discovered_ioc_keys:
        assert host_id in (host_a, host_b)


# ── is_run_over ───────────────────────────────────────────────────────────────

def test_is_run_over_false_at_the_start():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    assert verb_engine.is_run_over(run, cap_seconds=480) is False


def test_is_run_over_true_once_the_time_budget_is_exhausted():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    host_id = compiled.world.hosts[0].id
    # query_logs = 30s/call; 480s cap needs 16 calls.
    for _ in range(16):
        run = verb_engine.apply_verb(run, "query_logs", host_id).run
    assert run.elapsed_seconds >= 480
    assert verb_engine.is_run_over(run, cap_seconds=480) is True


def test_is_run_over_true_once_the_final_stage_has_fired_even_under_the_cap():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    run = _run_clock_past(run, final.trigger_seconds)
    # A generous cap that hasn't been reached — only the final-stage
    # condition should trigger this.
    assert run.elapsed_seconds < 10_000
    assert verb_engine.is_run_over(run, cap_seconds=10_000) is True


def test_is_run_over_respects_no_cap():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    assert verb_engine.is_run_over(run, cap_seconds=None) is False


# ── determine_outcome / compute_score ────────────────────────────────────────

def _final_stage(compiled):
    return next(s for s in compiled.stages if s.is_final)


def test_outcome_is_contained_before_the_final_stage_has_fired():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    assert verb_engine.determine_outcome(run) == "contained"


def test_outcome_is_contained_when_final_stage_target_is_isolated_before_it_fires():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    for host_id in final.compromises_host_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "contained"


def test_outcome_is_breached_when_final_stage_fires_completely_uncontained():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "breached"


def test_outcome_is_breached_spread_limited_when_final_fires_but_most_of_the_rest_is_contained():
    compiled = _compiled()
    final = _final_stage(compiled)
    other_target_ids = sorted({
        hid for s in compiled.stages if not s.is_final for hid in s.compromises_host_ids
    })
    assert other_target_ids, "test scenario must have non-final stages with real targets"

    run = verb_engine.new_run(compiled)
    for host_id in other_target_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    # Deliberately do NOT isolate the final stage's own target(s).
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "breached_spread_limited"


# ── Proportionate Response: collateral + grace (spec section 7's required
# cases) ─────────────────────────────────────────────────────────────────
#
# _compiled(seed=7)'s real geometry (confirmed by direct inspection, not
# assumed): 13 hosts total, on-attack-path (incl. final) = 3, decoy pool =
# 10 — big enough to exercise all 3 "final target stopped" states
# (contained / contained_at_cost / overreacted) distinctly against the
# hybrid grace formula (GRACE_FLOOR_WRONG_ISOLATIONS=1,
# OVERREACTED_COVERAGE_THRESHOLD=0.6).

def test_outcome_is_contained_with_one_wrong_isolation_within_the_grace_floor():
    compiled = _compiled()
    final = _final_stage(compiled)
    on_path = verb_engine._attack_path_host_ids(compiled)
    decoy = next(h.id for h in compiled.world.hosts if h.id not in on_path)

    run = verb_engine.new_run(compiled)
    for host_id in final.compromises_host_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    run = verb_engine.apply_verb(run, "isolate", decoy).run  # one honest mistake
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "contained"


def test_outcome_is_contained_at_cost_with_moderate_collateral_under_the_egregious_threshold():
    compiled = _compiled()
    final = _final_stage(compiled)
    on_path = verb_engine._attack_path_host_ids(compiled)
    decoys = [h.id for h in compiled.world.hosts if h.id not in on_path]
    assert len(decoys) >= 4, "fixture must have enough decoys to test the middle band"

    run = verb_engine.new_run(compiled)
    for host_id in final.compromises_host_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    # 4 of 10 decoys = 40% coverage: past the 1-mistake grace floor, under
    # the 60% egregious threshold.
    for decoy in decoys[:4]:
        run = verb_engine.apply_verb(run, "isolate", decoy).run
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "contained_at_cost"


def test_outcome_is_overreacted_when_isolating_every_revealed_host():
    """The exploit this whole spec exists to close: 'scan once, isolate
    every revealed host' must no longer read as a clean win."""
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    for host in compiled.world.hosts:
        run = verb_engine.apply_verb(run, "isolate", host.id).run
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "overreacted"


def test_grace_check_coverage_ratio_matches_wrong_isolated_over_decoy_pool():
    compiled = _compiled()
    on_path = verb_engine._attack_path_host_ids(compiled)
    decoys = [h.id for h in compiled.world.hosts if h.id not in on_path]

    run = verb_engine.new_run(compiled)
    for decoy in decoys[:3]:
        run = verb_engine.apply_verb(run, "isolate", decoy).run
    within_grace, coverage_ratio = verb_engine._grace_check(run)
    assert within_grace is False  # 3 wrong isolations > the 1-mistake grace floor
    assert coverage_ratio == pytest.approx(3 / len(decoys))


def test_compute_score_perfect_run_hits_100_score_pct():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    for placement in compiled.ioc_placements:
        run = verb_engine.apply_verb(run, "query_logs", placement.host_id).run
    breakdown = verb_engine.compute_score(run, "contained", cap_seconds=480)
    assert breakdown["score_pct"] == 100.0
    assert breakdown["penalty_total"] == 0
    assert breakdown["collateral"] == []
    assert breakdown["collateral_penalty"] == 0
    assert breakdown["evidence_found"] == breakdown["evidence_total"]
    assert breakdown["total_score"] > 0


def test_compute_score_penalty_lowers_score_pct_and_total_score():
    """Holds evidence-found constant between the two runs so the penalty's
    effect is isolated and visible — with zero evidence discovered in
    either run, score_pct floors at 0.0 for both regardless of penalties,
    which would make this comparison vacuous."""
    compiled = _compiled()
    off_path_host = next(h for h in compiled.world.hosts if h.id not in verb_engine._attack_path_host_ids(compiled))
    some_ioc_host_id = compiled.ioc_placements[0].host_id

    clean_run = verb_engine.apply_verb(verb_engine.new_run(compiled), "query_logs", some_ioc_host_id).run

    penalized_run = verb_engine.apply_verb(verb_engine.new_run(compiled), "query_logs", some_ioc_host_id).run
    penalized_run = verb_engine.apply_verb(penalized_run, "isolate", off_path_host.id).run  # wrong_isolation penalty

    clean_breakdown = verb_engine.compute_score(clean_run, "contained", cap_seconds=480)
    penalized_breakdown = verb_engine.compute_score(penalized_run, "contained", cap_seconds=480)

    assert clean_breakdown["evidence_found"] == penalized_breakdown["evidence_found"]
    assert penalized_breakdown["penalty_total"] == verb_engine.PRECISION_PENALTY
    # Isolating off_path_host is also collateral (never on the attack
    # path) — this penalized run pays both the wrong_isolation penalty AND
    # the collateral deduction for the same single action, by design (two
    # different things: penalty = "you guessed wrong", collateral = "a
    # real system went offline for no reason" — see verb_engine.compute_score).
    assert penalized_breakdown["collateral_penalty"] == verb_engine.DEFAULT_COLLATERAL_WEIGHT
    assert penalized_breakdown["score_pct"] < clean_breakdown["score_pct"]
    assert penalized_breakdown["total_score"] < clean_breakdown["total_score"]


def test_compute_score_breached_awards_no_speed_bonus():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "breached"
    breakdown = verb_engine.compute_score(run, "breached", cap_seconds=480)
    assert breakdown["speed_bonus"] == 0
    assert breakdown["outcome_base"] == 0


# ── Phase 2 acceptance re-verification (spec section 4 checklist) ──────────────
#
# Added during acceptance re-verification after compression_ratio scaling and
# BREACH_HEAD_START_SECONDS pre-fire (action_engine.py) — the two changes that
# made Colonial Pipeline's REAL authored timeline (gates spanning +4m to
# +49m) actually fit inside a real 480s/600s mode cap in the first place.
# `_SCENARIO` above has no compression_ratio, by design (existing tests in
# this file rely on its gates staying far outside any real cap — see e.g.
# `test_is_run_over_true_once_the_final_stage_has_fired_even_under_the_cap`'s
# 10_000s cap) — the tests below use a compressed copy specifically to
# exercise the realistic, now-actually-playable timeline.

_COMPRESSED_SCENARIO = dict(_SCENARIO, compression_ratio=8.0)

# seed=1 against _COMPRESSED_SCENARIO deterministically produces: two hosts
# (host-8, host-9) pre-fired to "foothold" by BREACH_HEAD_START_SECONDS at
# t=0, host-9 bound to the AUTH-009 (ip-matched) hidden_ioc, and a final
# stage at 367s (< both the 480s daily and 600s scenario cap) targeting
# host-1 — confirmed by direct inspection before writing this test, not
# assumed from the compiler's general behavior.
_CORE_LOOP_SEED = 1


def test_core_loop_scan_query_block_and_win_are_all_reachable_within_the_cap():
    """Phase 2 acceptance — the core loop, end to end, against a real
    compiled run (not mocked): scan reveals an already-in-progress breach,
    querying a compromised host surfaces its IOC (a real C2 IP), blocking
    that IP contains the matched host, and containing the final stage's
    real target before it fires wins — all inside the 480s daily cap."""
    compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=_CORE_LOOP_SEED)
    ip_ioc_host_ids = {p.host_id for p in compiled.ioc_placements if p.matches_on.get("ip")}
    run = verb_engine.new_run(compiled)

    # 1. scan reveals a seeded breach already in progress — not a clean map.
    result = verb_engine.apply_verb(run, "scan_network")
    run = result.run
    red_hosts = [n for n in result.delta["nodes"] if n["compromise_level"] != "none"]
    assert len(red_hosts) >= 1

    # 2. querying a compromised host that has evidence returns its IOC,
    # including a real C2 IP in the raw log text.
    target_host = next(n["id"] for n in red_hosts if n["id"] in ip_ioc_host_ids)
    result = verb_engine.apply_verb(run, "query_logs", target_host)
    run = result.run
    assert any("185.220.101.34" in ioc["raw_log"] for ioc in result.delta["revealed_iocs"])

    # 3. blocking that exact IP contains the matched host.
    result = verb_engine.apply_verb(run, "block_ip", "185.220.101.34")
    run = result.run
    assert result.delta["correct"] is True
    assert run.world.get_host(result.delta["host_id"]).isolated is True

    # 4. the win condition is reachable within the cap: isolate the final
    # stage's real target before it fires, let the clock pass it, and
    # confirm both "contained" and that it happened inside the DAILY cap
    # (the tighter of the two real caps — scenario mode's 600s is even
    # looser).
    final = next(s for s in compiled.stages if s.is_final)
    for host_id in final.compromises_host_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    while verb_engine.attacker_clock_seconds(run) <= final.trigger_seconds:
        run = verb_engine.apply_verb(run, "scan_network").run

    assert verb_engine.determine_outcome(run) == "contained"
    assert run.elapsed_seconds <= 480


def test_no_leak_on_initial_resync_despite_a_pre_fired_world():
    """Phase 2 acceptance criterion 2, re-verified against the new
    pre-fired-world behavior specifically: BREACH_HEAD_START_SECONDS means
    `run.world` already has compromised hosts the instant a run starts, but
    `earned_state_snapshot` (what a fresh WS connect resyncs to, per
    `action_run_ws_handler`) must still show nothing until a verb actually
    reveals it — compromise state existing server-side is not the same as
    it being earned. This exact interaction (pre-fired world + zero verbs
    played) did not exist before today's BREACH_HEAD_START_SECONDS change
    and had no prior test coverage."""
    compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=_CORE_LOOP_SEED)
    assert any(h.compromise_level != "none" for h in compiled.world.hosts), (
        "fixture must actually have a pre-fired host or this test proves nothing"
    )

    run = verb_engine.new_run(compiled)
    snapshot = verb_engine.earned_state_snapshot(run)
    assert snapshot == {"hosts": [], "revealed_iocs": [], "edges": []}


def test_five_seeded_runs_win_or_lose_by_strategy_not_luck():
    """Phase 2 acceptance criterion 4 (spec section 4 checklist): 'a skilled
    run can win with time to spare; a sloppy run can still partially
    recover ... play 5 seeded runs and confirm outcomes differ meaningfully
    by strategy, not luck.' For each of 5 seeds against the now-realistic
    compressed timeline: isolating the final stage's real target before it
    fires always wins; isolating an unrelated, off-attack-path host instead
    never does. Outcome tracks the choice made, not which seed it was."""
    for seed in range(1, 6):
        compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=seed)
        final = _final_stage(compiled)

        skilled = verb_engine.new_run(compiled)
        for host_id in final.compromises_host_ids:
            skilled = verb_engine.apply_verb(skilled, "isolate", host_id).run
        skilled = _run_clock_past(skilled, final.trigger_seconds)
        assert verb_engine.determine_outcome(skilled) == "contained", f"seed {seed}: isolating the real target must win"

        attack_path = verb_engine._attack_path_host_ids(compiled)
        off_path_host = next(h for h in compiled.world.hosts if h.id not in attack_path)
        sloppy = verb_engine.new_run(compiled)
        sloppy = verb_engine.apply_verb(sloppy, "isolate", off_path_host.id).run
        sloppy = _run_clock_past(sloppy, final.trigger_seconds)
        assert verb_engine.determine_outcome(sloppy) != "contained", f"seed {seed}: isolating the wrong host must not win"


def test_spending_the_full_cap_without_containment_loses_with_a_coherent_narrative():
    """Phase 2 acceptance criterion 3, REWRITTEN. The original checklist
    item ('a player who does nothing loses in <=8 minutes with a coherent
    narrative') assumed a real-time clock that advances independent of the
    player — it does not, and was never meant to: `RunState.elapsed_seconds`
    is a turn-based spend-clock, advanced only by verb costs
    (`action_run_store.py`'s own module docstring is explicit that this is
    intentional, not a bug). 'Do nothing' is incoherent against a clock that
    only moves when you act — there is no such thing as this player losing
    via the natural path at all, since the clock never leaves 0.

    The coherent replacement: a player who SPENDS the full time budget
    without containing the breach loses, and the loss is narratable — the
    final stage actually fired, and its real target host is left
    compromised and un-isolated. Verified end to end: spend the entire 480s
    daily cap on scan_network calls (a legitimate, if unproductive, play
    pattern — never isolating anything), and confirm all three: the run
    ends via the cap, the outcome is a loss/partial (never a win), and the
    final stage's target is genuinely compromised and unisolated in the
    resulting world state — not just a bare "loss" string with nothing
    behind it."""
    compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=_CORE_LOOP_SEED)
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)

    daily_cap = 480
    while run.elapsed_seconds < daily_cap:
        run = verb_engine.apply_verb(run, "scan_network").run

    assert verb_engine.is_run_over(run, cap_seconds=daily_cap) is True
    assert verb_engine.attacker_clock_seconds(run) >= final.trigger_seconds, "the final stage must actually have fired"

    outcome = verb_engine.determine_outcome(run)
    assert outcome in ("breached", "breached_spread_limited")

    final_hosts = [run.world.get_host(hid) for hid in final.compromises_host_ids]
    assert all(h.compromise_level != "none" and not h.isolated for h in final_hosts), (
        "coherent narrative: the final stage's real target must be left compromised and un-isolated"
    )


# ── Proportionate Response: determinism (spec section 7) ─────────────────────
#
# action_engine.compile_scenario's own determinism is already covered by
# test_action_engine.py's test_host_namespace_unification_stays_deterministic
# — this extends the same "same seed -> byte-identical" guarantee through
# verb_engine's outcome/score layer specifically, since Phase 4 ghost racing
# depends on same-seed replays producing the same OUTCOME and SCORE, not
# just the same compiled world.

def test_same_scenario_and_seed_produce_identical_outcome_and_score_across_independent_compiles():
    def _play(seed):
        compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=seed)
        final = _final_stage(compiled)
        run = verb_engine.new_run(compiled)
        # A fixed, mildly imprecise sequence (not just the "skilled" path) —
        # determinism must hold regardless of how clean the play is.
        for host in compiled.world.hosts[:2]:
            run = verb_engine.apply_verb(run, "isolate", host.id).run
        for host_id in final.compromises_host_ids:
            run = verb_engine.apply_verb(run, "isolate", host_id).run
        run = _run_clock_past(run, final.trigger_seconds)
        outcome = verb_engine.determine_outcome(run)
        score = verb_engine.compute_score(run, outcome, cap_seconds=480)
        return outcome, score

    outcome_a, score_a = _play(_CORE_LOOP_SEED)
    outcome_b, score_b = _play(_CORE_LOOP_SEED)
    assert outcome_a == outcome_b
    assert score_a == score_b


def test_tool_output_is_deterministic_across_independent_replays():
    """Diegetic tool output's own determinism requirement (tool_output.py's
    module docstring) — same scenario+seed+verb sequence must render
    byte-identical tool_output every time, same as outcome/score above."""
    def _play(seed):
        compiled = action_engine.compile_scenario(_COMPRESSED_SCENARIO, seed=seed)
        run = verb_engine.new_run(compiled)
        outputs = []
        result = verb_engine.apply_verb(run, "scan_network")
        outputs.append(result.delta["tool_output"])
        run = result.run
        for host in compiled.world.hosts[:2]:
            result = verb_engine.apply_verb(run, "query_logs", host.id)
            outputs.append(result.delta["tool_output"])
            run = result.run
            result = verb_engine.apply_verb(run, "isolate", host.id)
            outputs.append(result.delta["tool_output"])
            run = result.run
        result = verb_engine.apply_verb(run, "escalate")
        outputs.append(result.delta["tool_output"])
        return outputs

    outputs_a = _play(_CORE_LOOP_SEED)
    outputs_b = _play(_CORE_LOOP_SEED)
    assert outputs_a == outputs_b
    assert all(o["output"] for o in outputs_a), "every rendered tool_output must have real content"
