"""Tests for the Live Arena Mode Org Simulation Engine (Phase B).

These are plain, synchronous pytest functions — org_simulation.py is pure
(no DB access, no async I/O), so none of the async DB/client fixtures in
conftest.py are needed here. See docs/plans/live-arena-mode.md, Phase B
verification section, for the property-style determinism/fuzz requirements
these tests are built to satisfy.
"""
import random

import pytest

from app.services.org_simulation import (
    ORG_ARCHETYPES,
    ATTACKER_ACTION_TYPES,
    DEFENDER_ACTION_TYPES,
    OrgState,
    generate_org_state,
    apply_attacker_action,
    apply_defender_action,
    replay,
    _derive_rng,
)


ARCHETYPE_KEYS = list(ORG_ARCHETYPES.keys())


# ── 1. Determinism of generation ────────────────────────────────────────────

@pytest.mark.parametrize("seed", [1, 2, 42, 1337, 999999, 0, -7])
@pytest.mark.parametrize("archetype_key", ARCHETYPE_KEYS)
def test_generate_org_state_deterministic(seed, archetype_key):
    archetype = ORG_ARCHETYPES[archetype_key]
    state_a = generate_org_state(seed, archetype)
    state_b = generate_org_state(seed, archetype)
    assert state_a.to_dict() == state_b.to_dict()


def test_generate_org_state_different_seeds_differ():
    archetype = ORG_ARCHETYPES["energy_utility"]
    state_a = generate_org_state(1, archetype)
    state_b = generate_org_state(2, archetype)
    assert state_a.to_dict() != state_b.to_dict()


def test_generate_org_state_shape_matches_archetype():
    for key, archetype in ORG_ARCHETYPES.items():
        state = generate_org_state(12345, archetype)
        host_lo, host_hi = archetype["host_count_range"]
        seg_lo, seg_hi = archetype["segment_count_range"]
        assert host_lo <= len(state.hosts) <= host_hi
        assert seg_lo <= len(state.segments) <= seg_hi
        assert len(state.detection_rules) > 0
        assert len(state.credentials) > 0
        # every host references a real segment
        segment_ids = {s.id for s in state.segments}
        for h in state.hosts:
            assert h.network_segment_id in segment_ids
        # every credential's valid_on_host_ids reference real hosts
        host_ids = {h.id for h in state.hosts}
        for c in state.credentials:
            assert set(c.valid_on_host_ids).issubset(host_ids)


def test_org_state_roundtrip_to_from_dict():
    state = generate_org_state(555, ORG_ARCHETYPES["small_healthcare"])
    rebuilt = OrgState.from_dict(state.to_dict())
    assert rebuilt.to_dict() == state.to_dict()


# ── 2. Determinism under a fixed action sequence via replay() ─────────────

def _fixed_action_sequence() -> list[dict]:
    return [
        {"sequence_number": 0, "actor": "attacker", "action_type": "discover_segment", "payload": {"segment_id": "seg-1"}},
        {"sequence_number": 1, "actor": "attacker", "action_type": "gain_foothold", "payload": {"host_id": "host-2"}},
        {"sequence_number": 2, "actor": "attacker", "action_type": "dump_credentials", "payload": {"host_id": "host-2"}},
        {"sequence_number": 3, "actor": "defender", "action_type": "increase_monitoring", "payload": {"segment_id": "seg-1"}},
        {"sequence_number": 4, "actor": "attacker", "action_type": "escalate_privilege", "payload": {"host_id": "host-2"}},
        {"sequence_number": 5, "actor": "defender", "action_type": "isolate_host", "payload": {"host_id": "host-3"}},
        {"sequence_number": 6, "actor": "attacker", "action_type": "lateral_move", "payload": {"credential_id": "cred-1", "target_host_id": "host-3"}},
    ]


@pytest.mark.parametrize("seed", [7, 100, 2024])
def test_replay_deterministic_state_and_events(seed):
    actions = _fixed_action_sequence()
    state_a, events_a = replay(seed, "energy_utility", actions)
    state_b, events_b = replay(seed, "energy_utility", actions)
    assert state_a.to_dict() == state_b.to_dict()
    assert events_a == events_b


def test_replay_prefix_matches_full_run_up_to_divergence():
    """Replaying a shorter prefix of the same log reproduces identical
    events for every action up to the truncation point (Phase G's future
    branching replay relies on this)."""
    seed = 42
    actions = _fixed_action_sequence()
    full_state, full_events = replay(seed, "energy_utility", actions)
    prefix_state, prefix_events = replay(seed, "energy_utility", actions[:4])
    assert full_events[:4] == prefix_events
    # And the prefix result is itself reproducible.
    prefix_state_2, prefix_events_2 = replay(seed, "energy_utility", actions[:4])
    assert prefix_state.to_dict() == prefix_state_2.to_dict()
    assert prefix_events == prefix_events_2


def test_derive_rng_deterministic_and_seed_sensitive():
    r1 = _derive_rng(42, 3)
    r2 = _derive_rng(42, 3)
    assert r1.random() == r2.random()

    r3 = _derive_rng(42, 4)
    r4 = _derive_rng(43, 3)
    # Different sequence_number or seed should (with overwhelming
    # probability) produce a different stream.
    assert _derive_rng(42, 3).random() != r3.random()
    assert _derive_rng(42, 3).random() != r4.random()


@pytest.mark.parametrize("seed", [1, 42, 12345, 999999])
def test_derive_rng_no_sign_symmetry_collision(seed):
    """Regression test for the sign-symmetry collision: CPython's
    random.Random(x) and random.Random(-x) can produce identical/mirrored
    streams for many x, so (seed, -seed) pairs must not collide once
    _derive_rng hashes its inputs instead of doing raw signed arithmetic."""
    for sequence_number in range(5):
        r_pos = _derive_rng(seed, sequence_number)
        r_neg = _derive_rng(-seed, sequence_number)
        assert r_pos.random() != r_neg.random()

    # Still deterministic for negative seeds specifically.
    a = _derive_rng(-seed, 3)
    b = _derive_rng(-seed, 3)
    assert a.random() == b.random()


# ── 3. Fuzz / crash-safety ──────────────────────────────────────────────────

_ALL_ACTION_TYPES = list(ATTACKER_ACTION_TYPES) + list(DEFENDER_ACTION_TYPES)


def _random_structurally_valid_action(fuzz_rng: random.Random, state: OrgState, sequence_number: int) -> dict:
    """Build an action with a real action_type and IDs drawn from the
    generated org, but WITHOUT checking whether preconditions are actually
    met — this is exactly the fuzz input the plan calls for."""
    actor = fuzz_rng.choice(["attacker", "defender"])
    action_type = fuzz_rng.choice(ATTACKER_ACTION_TYPES if actor == "attacker" else DEFENDER_ACTION_TYPES)

    host_ids = [h.id for h in state.hosts] or ["host-nonexistent"]
    segment_ids = [s.id for s in state.segments] or ["seg-nonexistent"]
    credential_ids = [c.id for c in state.credentials] or ["cred-nonexistent"]

    payload: dict = {}
    if action_type in ("discover_host", "gain_foothold", "dump_credentials", "escalate_privilege", "deploy_impact", "isolate_host"):
        payload["host_id"] = fuzz_rng.choice(host_ids)
    if action_type in ("discover_segment", "increase_monitoring"):
        payload["segment_id"] = fuzz_rng.choice(segment_ids)
    if action_type == "lateral_move":
        payload["credential_id"] = fuzz_rng.choice(credential_ids)
        payload["target_host_id"] = fuzz_rng.choice(host_ids)
    if action_type == "disable_credential":
        payload["credential_id"] = fuzz_rng.choice(credential_ids)
    if action_type == "patch_host":
        payload["host_id"] = fuzz_rng.choice(host_ids)
        if fuzz_rng.random() < 0.5:
            payload["cve"] = "CVE-0000-0000"

    return {"sequence_number": sequence_number, "actor": actor, "action_type": action_type, "payload": payload}


@pytest.mark.parametrize("seed", list(range(20)))
def test_fuzz_random_action_sequences_never_crash(seed):
    fuzz_rng = random.Random(f"fuzz-{seed}")
    archetype_key = fuzz_rng.choice(ARCHETYPE_KEYS)
    archetype = ORG_ARCHETYPES[archetype_key]
    state = generate_org_state(seed, archetype)

    actions = []
    for i in range(30):
        actions.append(_random_structurally_valid_action(fuzz_rng, state, i))

    # Should never raise, regardless of whether individual actions'
    # preconditions are actually satisfied.
    final_state, events = replay(seed, archetype_key, actions)
    assert isinstance(final_state, OrgState)
    assert len(events) == len(actions)
    for ev in events:
        assert "detected" in ev
        assert "alert" in ev
        if not ev["detected"]:
            assert ev["alert"] is None


@pytest.mark.parametrize("seed", list(range(20)))
def test_fuzz_apply_attacker_action_directly_never_crashes(seed):
    """Also fuzz apply_attacker_action directly (not just via replay) with
    garbage/missing payload fields, confirming graceful no-op behavior."""
    fuzz_rng = random.Random(f"direct-fuzz-{seed}")
    state = generate_org_state(seed, ORG_ARCHETYPES["small_healthcare"])
    rng = random.Random(seed * 31 + 1)

    garbage_actions = [
        {"action_type": "lateral_move", "payload": {}},
        {"action_type": "gain_foothold", "payload": {"host_id": "does-not-exist"}},
        {"action_type": "dump_credentials", "payload": {"host_id": None}},
        {"action_type": "escalate_privilege", "payload": {}},
        {"action_type": "not_a_real_action", "payload": {"host_id": "host-1"}},
        {"action_type": None, "payload": {}},
        {},
    ]
    for action in garbage_actions:
        new_state, detected, alert = apply_attacker_action(state, action, rng)
        assert isinstance(new_state, OrgState)
        assert detected is False
        assert alert is None
        # Unrecognized/invalid actions must not mutate state.
        assert new_state.to_dict() == state.to_dict()


@pytest.mark.parametrize("seed", list(range(10)))
def test_fuzz_apply_defender_action_directly_never_crashes(seed):
    state = generate_org_state(seed, ORG_ARCHETYPES["small_healthcare"])
    garbage_actions = [
        {"action_type": "isolate_host", "payload": {"host_id": "nope"}},
        {"action_type": "disable_credential", "payload": {}},
        {"action_type": "patch_host", "payload": {"host_id": "nope", "cve": "CVE-9999-9999"}},
        {"action_type": "increase_monitoring", "payload": {"segment_id": "nope"}},
        {"action_type": "unknown_type", "payload": {}},
        {},
    ]
    for action in garbage_actions:
        new_state = apply_defender_action(state, action)
        assert isinstance(new_state, OrgState)


# ── 4. Real state-graph logic end to end ───────────────────────────────────

def _hand_built_state() -> OrgState:
    """A small, hand-built OrgState (not generated) so this test's
    preconditions are exact and don't depend on generate_org_state's random
    credential-overlap shape landing a particular way for a given seed."""
    from app.services.org_simulation import Host, NetworkSegment, Credential, DetectionRule

    segments = (
        NetworkSegment(id="seg-1", name="corp", monitored=False, reachable_from=("seg-2",)),
        NetworkSegment(id="seg-2", name="dmz", monitored=False, reachable_from=("seg-1",)),
    )
    hosts = (
        Host(id="host-src", hostname="CORP-WKS-01", role="workstation", network_segment_id="seg-1"),
        Host(id="host-target", hostname="CORP-SRV-01", role="server", network_segment_id="seg-1"),
        Host(id="host-unreachable", hostname="DMZ-SRV-01", role="server", network_segment_id="seg-2"),
    )
    credentials = (
        # Valid on both host-src and host-target — this is the credential
        # dump_credentials(host-src) should harvest and lateral_move should
        # then be able to use against host-target.
        Credential(id="cred-multi", username="svc_backup", privilege="admin",
                    valid_on_host_ids=("host-src", "host-target"), harvested=False, disabled=False),
        # Valid ONLY on host-unreachable — never harvested by dumping on
        # host-src, so using it against host-unreachable must fail even
        # though it's a "real" credential in the org.
        Credential(id="cred-other", username="jsmith", privilege="user",
                    valid_on_host_ids=("host-unreachable",), harvested=False, disabled=False),
    )
    # No detection rules fire (base_detection_probability=0) so this test's
    # success/failure assertions are about state-graph logic, not RNG luck.
    detection_rules = (
        DetectionRule(id="rule-silent", technique_id="T1078", base_detection_probability=0.0),
        DetectionRule(id="rule-silent-2", technique_id="T1003.001", base_detection_probability=0.0),
        DetectionRule(id="rule-silent-3", technique_id="T1550.002", base_detection_probability=0.0),
    )
    return OrgState(hosts=hosts, segments=segments, credentials=credentials, detection_rules=detection_rules)


def test_lateral_move_requires_harvested_valid_non_disabled_credential():
    state = _hand_built_state()
    rng = random.Random(1)

    # (a) No foothold anywhere yet: lateral_move must fail cleanly even
    # though cred-multi is a real credential valid on host-target.
    action_lateral = {
        "action_type": "lateral_move",
        "payload": {"credential_id": "cred-multi", "target_host_id": "host-target"},
        "sequence_number": 0,
    }
    state0, detected0, alert0 = apply_attacker_action(state, action_lateral, rng)
    assert detected0 is False and alert0 is None
    assert state0.to_dict() == state.to_dict()

    # (b) Gain a foothold on host-src, then attempt lateral_move BEFORE
    # dumping credentials — cred-multi isn't harvested yet, so it must
    # still fail even though the attacker now controls an adjacent host.
    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-src"}}, random.Random(2)
    )
    assert state1.get_host("host-src").compromise_level == "foothold"

    state2, detected1, alert1 = apply_attacker_action(state1, action_lateral, random.Random(3))
    assert state2.get_host("host-target").compromise_level == "none"

    # (c) Dump credentials on host-src — harvests cred-multi (valid on
    # host-src) but must NOT harvest cred-other (not valid on host-src).
    state3, _, _ = apply_attacker_action(
        state1, {"action_type": "dump_credentials", "payload": {"host_id": "host-src"}}, random.Random(4)
    )
    assert state3.get_credential("cred-multi").harvested is True
    assert state3.get_credential("cred-other").harvested is False

    # (d) NOW lateral_move with the harvested, valid, non-disabled
    # credential must succeed.
    state4, detected2, alert2 = apply_attacker_action(state3, action_lateral, random.Random(5))
    assert state4.get_host("host-target").compromise_level != "none"

    # (e) Using cred-other (real credential, but NOT valid on host-target
    # and never harvested) against host-target must fail cleanly.
    action_wrong_cred = {
        "action_type": "lateral_move",
        "payload": {"credential_id": "cred-other", "target_host_id": "host-target"},
        "sequence_number": 6,
    }
    state5, detected3, alert3 = apply_attacker_action(state4, action_wrong_cred, random.Random(6))
    assert state5.to_dict() == state4.to_dict()

    # (f) Disable cred-multi, then confirm lateral_move to a fresh target
    # (host-unreachable is out of reach anyway, so re-use host-target on a
    # freshly reset state to isolate "disabled" as the sole variable).
    state6 = apply_defender_action(state3, {"action_type": "disable_credential", "payload": {"credential_id": "cred-multi"}})
    assert state6.get_credential("cred-multi").disabled is True
    state7, detected4, alert4 = apply_attacker_action(state6, action_lateral, random.Random(7))
    assert state7.get_host("host-target").compromise_level == "none"
    assert state7.to_dict() == state6.to_dict()

    # (g) Isolating host-target must block lateral_move even with a valid,
    # harvested, non-disabled credential.
    state8 = apply_defender_action(state3, {"action_type": "isolate_host", "payload": {"host_id": "host-target"}})
    assert state8.get_host("host-target").isolated is True
    state9, detected5, alert5 = apply_attacker_action(state8, action_lateral, random.Random(8))
    assert state9.get_host("host-target").compromise_level == "none"
    assert state9.to_dict() == state8.to_dict()

    # (h) cred-other is never valid on host-unreachable's segment path from
    # a compromised host (seg-2 only reachable via seg-1, and host-src is
    # compromised in seg-1) — but even WITH reachability, using it requires
    # it be harvested first. Confirm the unharvested case fails cleanly.
    action_unreachable = {
        "action_type": "lateral_move",
        "payload": {"credential_id": "cred-other", "target_host_id": "host-unreachable"},
        "sequence_number": 9,
    }
    state10, detected6, alert6 = apply_attacker_action(state3, action_unreachable, random.Random(9))
    assert state10.get_host("host-unreachable").compromise_level == "none"
    assert state10.to_dict() == state3.to_dict()


def test_dump_credentials_only_harvests_credentials_valid_on_that_host():
    seed = 99
    state = generate_org_state(seed, ORG_ARCHETYPES["small_healthcare"])
    host = state.hosts[0]
    state2, _, _ = apply_attacker_action(state, {"action_type": "gain_foothold", "payload": {"host_id": host.id}}, random.Random(1))
    state3, _, _ = apply_attacker_action(state2, {"action_type": "dump_credentials", "payload": {"host_id": host.id}}, random.Random(2))

    for cred in state3.credentials:
        original = state.get_credential(cred.id)
        if host.id in original.valid_on_host_ids and not original.disabled:
            assert cred.harvested is True
        else:
            assert cred.harvested == original.harvested


def test_alert_shape_matches_existing_convention():
    """Any alert emitted must match the existing seed.py alert_sequence
    shape exactly: timestamp, severity, source_system, rule_id,
    description, raw_log — nothing more, nothing less required."""
    required_keys = {"timestamp", "severity", "source_system", "rule_id", "description", "raw_log"}
    found_alert = False
    for seed in range(50):
        state = generate_org_state(seed, ORG_ARCHETYPES["energy_utility"])
        host = state.hosts[0]
        state2, _, _ = apply_attacker_action(state, {"action_type": "gain_foothold", "payload": {"host_id": host.id}}, random.Random(0))
        for detect_seed in range(20):
            _, detected, alert = apply_attacker_action(
                state, {"action_type": "gain_foothold", "payload": {"host_id": host.id}}, random.Random(detect_seed)
            )
            if detected:
                found_alert = True
                assert required_keys.issubset(alert.keys())
                break
        if found_alert:
            break
    assert found_alert, "expected at least one detection to fire across 50 seeds x 20 rng draws"


def test_isolated_host_unreachable_for_lateral_move_end_to_end():
    """Mirrors Phase C's verification requirement in miniature: isolating a
    host actually removes it from what a subsequent lateral-movement action
    can reach, computed against real state."""
    seed = 777
    state = generate_org_state(seed, ORG_ARCHETYPES["energy_utility"])
    cred = next((c for c in state.credentials if len(c.valid_on_host_ids) >= 1), None)
    assert cred is not None
    target_host_id = cred.valid_on_host_ids[0]

    # Manually harvest the credential to isolate the "isolation" variable.
    from dataclasses import asdict
    from app.services.org_simulation import Credential
    harvested_creds = tuple(
        Credential(**{**asdict(c), "valid_on_host_ids": c.valid_on_host_ids, "harvested": True}) if c.id == cred.id else c
        for c in state.credentials
    )
    state_with_harvested = OrgState(
        hosts=state.hosts, segments=state.segments, credentials=harvested_creds,
        detection_rules=state.detection_rules, global_flags=state.global_flags,
    )
    # Give the attacker a foothold somewhere so segment reachability check can pass.
    source_host = next(h for h in state.hosts if h.id != target_host_id)
    state_with_foothold, _, _ = apply_attacker_action(
        state_with_harvested, {"action_type": "gain_foothold", "payload": {"host_id": source_host.id}}, random.Random(1)
    )

    # Isolate the target host.
    state_isolated = apply_defender_action(state_with_foothold, {"action_type": "isolate_host", "payload": {"host_id": target_host_id}})
    assert state_isolated.get_host(target_host_id).isolated is True

    result_state, detected, alert = apply_attacker_action(
        state_isolated,
        {"action_type": "lateral_move", "payload": {"credential_id": cred.id, "target_host_id": target_host_id}},
        random.Random(2),
    )
    assert result_state.get_host(target_host_id).compromise_level == "none"
    assert result_state.to_dict() == state_isolated.to_dict()


# ── 5. Regression tests for reviewed bugs ───────────────────────────────────

def _two_host_state(cve_on_target: bool = True) -> OrgState:
    """Small hand-built state with two hosts, used to exercise
    escalate_privilege / deploy_impact preconditions precisely."""
    from app.services.org_simulation import Host, NetworkSegment, DetectionRule

    segments = (
        NetworkSegment(id="seg-1", name="corp", monitored=False, reachable_from=()),
    )
    hosts = (
        Host(
            id="host-a", hostname="CORP-WKS-01", role="workstation", network_segment_id="seg-1",
            unpatched_cves=("CVE-2021-34527",) if cve_on_target else (),
        ),
        Host(id="host-b", hostname="CORP-WKS-02", role="workstation", network_segment_id="seg-1"),
    )
    # No detection rules fire, so success/failure assertions are about
    # state-graph logic, not RNG luck.
    detection_rules = (
        DetectionRule(id="rule-silent-t1068", technique_id="T1068", base_detection_probability=0.0),
        DetectionRule(id="rule-silent-t1486", technique_id="T1486", base_detection_probability=0.0),
    )
    return OrgState(hosts=hosts, segments=segments, credentials=(), detection_rules=detection_rules)


def test_escalate_privilege_fails_without_unpatched_cve():
    state = _two_host_state(cve_on_target=False)
    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-a"}}, random.Random(1)
    )
    assert state1.get_host("host-a").compromise_level == "foothold"

    state2, detected, alert = apply_attacker_action(
        state1, {"action_type": "escalate_privilege", "payload": {"host_id": "host-a"}}, random.Random(2)
    )
    # No unpatched CVEs on host-a -> escalation must fail gracefully.
    assert state2.get_host("host-a").compromise_level == "foothold"
    assert state2.to_dict() == state1.to_dict()
    assert detected is False
    assert alert is None


def test_escalate_privilege_succeeds_with_unpatched_cve():
    state = _two_host_state(cve_on_target=True)
    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-a"}}, random.Random(1)
    )
    assert state1.get_host("host-a").compromise_level == "foothold"

    state2, detected, alert = apply_attacker_action(
        state1, {"action_type": "escalate_privilege", "payload": {"host_id": "host-a"}}, random.Random(2)
    )
    assert state2.get_host("host-a").compromise_level == "admin"


def test_deploy_impact_fails_with_single_foothold_only():
    """A single gain_foothold must NOT be sufficient to trigger the
    match-ending deploy_impact action (the original bug)."""
    state = _two_host_state()
    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-a"}}, random.Random(1)
    )
    assert state1.get_host("host-a").compromise_level == "foothold"

    state2, detected, alert = apply_attacker_action(
        state1, {"action_type": "deploy_impact", "payload": {"host_id": "host-a"}}, random.Random(2)
    )
    assert state2.to_dict() == state1.to_dict()
    assert detected is False
    assert alert is None
    assert "impact_deployed" not in state2.global_flags


def test_deploy_impact_fails_with_only_one_host_at_admin():
    """Target host at admin, but no OTHER host at admin-or-higher: still
    not enough footprint per the new precondition (min 2 hosts)."""
    state = _two_host_state()
    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-a"}}, random.Random(1)
    )
    state2, _, _ = apply_attacker_action(
        state1, {"action_type": "escalate_privilege", "payload": {"host_id": "host-a"}}, random.Random(2)
    )
    assert state2.get_host("host-a").compromise_level == "admin"

    state3, detected, alert = apply_attacker_action(
        state2, {"action_type": "deploy_impact", "payload": {"host_id": "host-a"}}, random.Random(3)
    )
    assert state3.to_dict() == state2.to_dict()
    assert detected is False
    assert alert is None


def test_deploy_impact_succeeds_once_two_hosts_at_admin():
    from app.services.org_simulation import Host

    state = _two_host_state()
    # Manually promote host-b to admin too (host-b has no CVEs in the
    # fixture, so drive it directly rather than via escalate_privilege).
    state = OrgState(
        hosts=tuple(
            Host(id="host-b", hostname="CORP-WKS-02", role="workstation", network_segment_id="seg-1", compromise_level="admin")
            if h.id == "host-b" else h
            for h in state.hosts
        ),
        segments=state.segments, credentials=state.credentials,
        detection_rules=state.detection_rules, global_flags=state.global_flags,
    )

    state1, _, _ = apply_attacker_action(
        state, {"action_type": "gain_foothold", "payload": {"host_id": "host-a"}}, random.Random(1)
    )
    state2, _, _ = apply_attacker_action(
        state1, {"action_type": "escalate_privilege", "payload": {"host_id": "host-a"}}, random.Random(2)
    )
    assert state2.get_host("host-a").compromise_level == "admin"
    assert state2.get_host("host-b").compromise_level == "admin"

    state3, detected, alert = apply_attacker_action(
        state2, {"action_type": "deploy_impact", "payload": {"host_id": "host-a"}}, random.Random(3)
    )
    assert detected is True
    assert alert is not None
    assert state3.global_flags.get("impact_deployed") is True
    # Fallback alert (no detection rule conditions satisfied) must not
    # misattribute detection to EDR coverage that isn't there.
    assert alert["source_system"] != "EDR"


def test_replay_skips_non_dict_action_entries_gracefully():
    """A malformed action log entry (None, a bare string, etc.) must be
    skipped rather than crashing the whole replay — and valid entries
    later in the log must still be applied correctly."""
    actions = [
        None,
        "garbage",
        42,
        [1, 2, 3],
        {"sequence_number": 4, "actor": "attacker", "action_type": "gain_foothold", "payload": {"host_id": "host-1"}},
    ]
    final_state, events = replay(42, "small_healthcare", actions)
    assert len(events) == len(actions)
    # The one valid action still gets applied.
    assert final_state.get_host("host-1").compromise_level == "foothold"
    # The valid action's event reflects the real action_type.
    assert events[-1]["action_type"] == "gain_foothold"
