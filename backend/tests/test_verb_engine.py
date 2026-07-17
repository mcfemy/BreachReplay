"""
Tests for backend/app/services/verb_engine.py (Phase 2, Item 1 — verb
application layer). Pure, synchronous tests — apply_verb does no I/O.
"""
import json
import re

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
    # would show, not under-report it.
    assert result.delta == {
        "correct": True,
        "host_id": ip_placement.host_id,
        "revealed_iocs": [ip_placement.to_dict()],
    }


def test_block_ip_wrong_address_records_a_penalty_and_isolates_nothing():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    result = verb_engine.apply_verb(run, "block_ip", "9.9.9.9")
    assert result.delta == {"correct": False}
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
    assert result.delta == {"correct": False}
    assert any(p["type"] == "wrong_reset_creds" for p in result.run.penalties)


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
    or any hidden_iocs the player hasn't earned yet."""
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


def test_outcome_is_win_before_the_final_stage_has_fired():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    assert verb_engine.determine_outcome(run) == "win"


def test_outcome_is_win_when_final_stage_target_is_isolated_before_it_fires():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    for host_id in final.compromises_host_ids:
        run = verb_engine.apply_verb(run, "isolate", host_id).run
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "win"


def test_outcome_is_loss_when_final_stage_fires_completely_uncontained():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "loss"


def test_outcome_is_partial_when_final_fires_but_most_of_the_rest_is_contained():
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
    assert verb_engine.determine_outcome(run) == "partial"


def test_compute_score_perfect_run_hits_100_score_pct():
    compiled = _compiled()
    run = verb_engine.new_run(compiled)
    for placement in compiled.ioc_placements:
        run = verb_engine.apply_verb(run, "query_logs", placement.host_id).run
    breakdown = verb_engine.compute_score(run, "win", cap_seconds=480)
    assert breakdown["score_pct"] == 100.0
    assert breakdown["penalty_total"] == 0
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

    clean_breakdown = verb_engine.compute_score(clean_run, "win", cap_seconds=480)
    penalized_breakdown = verb_engine.compute_score(penalized_run, "win", cap_seconds=480)

    assert clean_breakdown["evidence_found"] == penalized_breakdown["evidence_found"]
    assert penalized_breakdown["penalty_total"] == verb_engine.PRECISION_PENALTY
    assert penalized_breakdown["score_pct"] < clean_breakdown["score_pct"]
    assert penalized_breakdown["total_score"] < clean_breakdown["total_score"]


def test_compute_score_loss_awards_no_speed_bonus():
    compiled = _compiled()
    final = _final_stage(compiled)
    run = verb_engine.new_run(compiled)
    run = _run_clock_past(run, final.trigger_seconds)
    assert verb_engine.determine_outcome(run) == "loss"
    breakdown = verb_engine.compute_score(run, "loss", cap_seconds=480)
    assert breakdown["speed_bonus"] == 0
    assert breakdown["outcome_base"] == 0
