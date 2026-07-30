"""
Tests for backend/app/services/tool_output.py — diegetic tool output.
Pure, synchronous unit tests directly against the render_* functions
(no apply_verb/RunState needed): each one takes exactly the already-
filtered inputs verb_engine.apply_verb passes it, so leak-safety is
testable at the boundary — "given this exact input, does the output ever
say more than the input contains" — without needing a full compiled run.

Integration-level coverage (that apply_verb actually WIRES the correct
already-filtered data into these functions, not something broader) lives
in test_verb_engine.py's test_no_verb_response_ever_leaks_unrevealed_
hidden_state, which already scans tool_output for free since it's nested
inside each verb's own delta.
"""
import re

from app.services import tool_output
from app.services.action_engine import IOCPlacement
from app.services.org_simulation import Host

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_HOST_A = Host(id="host-1", hostname="CORP-DC-01", role="domain_controller", network_segment_id="seg-corp")
_HOST_B = Host(id="host-2", hostname="OT-HISTORIAN-01", role="scada", network_segment_id="seg-ot")
_HOST_C = Host(id="host-3", hostname="FIN-SVR-04", role="server", network_segment_id="seg-corp")

_IOC_A = IOCPlacement(
    host_id="host-1", description="Encoded PowerShell", severity="high",
    source_system="EDR", rule_id="EDR-045", raw_log="proc=powershell.exe host=CORP-DC-01",
    matches_on={"hostname": "CORP-DC-01"},
)
_IOC_B = IOCPlacement(
    host_id="host-1", description="Suspicious login", severity="medium",
    source_system="Auth", rule_id="AUTH-009", raw_log="auth=success src_ip=185.220.101.34",
    matches_on={"ip": "185.220.101.34"},
)


# ── scan_network / nmap ───────────────────────────────────────────────────────

def test_render_scan_network_lists_every_given_host_exactly_once():
    result = tool_output.render_scan_network(seed=42, hosts=[_HOST_A, _HOST_B, _HOST_C], elapsed_seconds=90)
    assert result["tool"] == "nmap"
    assert result["command"].startswith("nmap -sn ")
    for host in (_HOST_A, _HOST_B, _HOST_C):
        assert result["output"].count(f"Nmap scan report for {host.hostname}") == 1
    assert "Nmap done: 3 IP addresses (3 hosts up)" in result["output"]


def test_render_scan_network_never_mentions_a_host_not_given():
    result = tool_output.render_scan_network(seed=42, hosts=[_HOST_A], elapsed_seconds=0)
    assert _HOST_B.hostname not in result["output"]
    assert _HOST_C.hostname not in result["output"]


def test_render_scan_network_is_deterministic():
    a = tool_output.render_scan_network(seed=7, hosts=[_HOST_A, _HOST_B], elapsed_seconds=45)
    b = tool_output.render_scan_network(seed=7, hosts=[_HOST_A, _HOST_B], elapsed_seconds=45)
    assert a == b


def test_render_scan_network_differs_across_seeds():
    a = tool_output.render_scan_network(seed=7, hosts=[_HOST_A], elapsed_seconds=0)
    b = tool_output.render_scan_network(seed=8, hosts=[_HOST_A], elapsed_seconds=0)
    assert a["output"] != b["output"]


def test_render_scan_network_handles_no_hosts():
    result = tool_output.render_scan_network(seed=1, hosts=[], elapsed_seconds=0)
    assert "0 hosts up" in result["output"]


# ── query_logs / Splunk SPL ──────────────────────────────────────────────────

def test_render_query_logs_only_includes_given_placements():
    result = tool_output.render_query_logs(seed=1, host=_HOST_A, revealed_iocs=[_IOC_A], elapsed_seconds=30)
    assert _IOC_A.rule_id in result["output"]
    assert _IOC_A.raw_log in result["output"]
    assert _IOC_B.rule_id not in result["output"]
    assert _IOC_B.raw_log not in result["output"]


def test_render_query_logs_with_no_placements_reports_zero_results():
    result = tool_output.render_query_logs(seed=1, host=_HOST_A, revealed_iocs=[], elapsed_seconds=0)
    assert "0 results" in result["output"]
    # Even with nothing revealed, the command itself only ever names the
    # host the player actually targeted — never a stage/technique.
    assert _HOST_A.hostname in result["command"]


def test_render_query_logs_never_leaks_matches_on():
    """matches_on is the answer to block_ip/reset_creds — must never appear
    in query_logs' rendering even though IOCPlacement carries it."""
    result = tool_output.render_query_logs(seed=1, host=_HOST_A, revealed_iocs=[_IOC_B], elapsed_seconds=0)
    assert "185.220.101.34" not in result["command"]
    # The IP DOES legitimately appear in raw_log (that's the point of
    # block_ip's answer being discoverable through play) — only the
    # matches_on dict itself, not raw_log text, is off-limits.
    assert "matches_on" not in str(result)


def test_render_query_logs_is_deterministic():
    a = tool_output.render_query_logs(seed=5, host=_HOST_A, revealed_iocs=[_IOC_A], elapsed_seconds=60)
    b = tool_output.render_query_logs(seed=5, host=_HOST_A, revealed_iocs=[_IOC_A], elapsed_seconds=60)
    assert a == b


# ── image_disk / dd + sha256sum ──────────────────────────────────────────────

def test_render_image_disk_hash_is_a_valid_sha256_and_deterministic():
    a = tool_output.render_image_disk(seed=3, host=_HOST_A, revealed_iocs=[], unpatched_cves=[], edr_installed=False, elapsed_seconds=0)
    b = tool_output.render_image_disk(seed=3, host=_HOST_A, revealed_iocs=[], unpatched_cves=[], edr_installed=False, elapsed_seconds=0)
    match = re.search(r"([0-9a-f]{64})  ", a["output"])
    assert match is not None, "output must contain a real-format sha256sum line"
    assert _SHA256_RE.match(match.group(1))
    assert a == b


def test_render_image_disk_differs_by_host_even_at_the_same_seed():
    a = tool_output.render_image_disk(seed=3, host=_HOST_A, revealed_iocs=[], unpatched_cves=[], edr_installed=False, elapsed_seconds=0)
    b = tool_output.render_image_disk(seed=3, host=_HOST_B, revealed_iocs=[], unpatched_cves=[], edr_installed=False, elapsed_seconds=0)
    assert a["output"] != b["output"]


def test_render_image_disk_only_includes_given_placements_and_forensics():
    result = tool_output.render_image_disk(
        seed=1, host=_HOST_A, revealed_iocs=[_IOC_A],
        unpatched_cves=["CVE-2021-1234"], edr_installed=True, elapsed_seconds=0,
    )
    assert "1 indicator" in result["output"]
    assert "EDR agent: present" in result["output"]
    assert "Unpatched CVEs on record: 1" in result["output"]
    assert _IOC_B.rule_id not in result["output"]


# ── interview_user / notes ───────────────────────────────────────────────────

def test_render_interview_user_lists_only_given_credentials():
    creds = [{"credential_id": "c1", "username": "svc_backup", "privilege": "admin"}]
    result = tool_output.render_interview_user(_HOST_A, creds)
    assert result["tool"] == "Interview Notes"
    assert result["command"] is None
    assert "svc_backup" in result["output"]


def test_render_interview_user_with_no_credentials_says_so():
    result = tool_output.render_interview_user(_HOST_A, [])
    assert "No user on record" in result["output"]


# ── block_ip / iptables ───────────────────────────────────────────────────────

def test_render_block_ip_only_ever_echoes_the_submitted_target():
    result = tool_output.render_block_ip("203.0.113.4")
    assert "203.0.113.4" in result["command"]
    assert "203.0.113.4" in result["output"]
    assert result["tool"] == "iptables"


def test_render_block_ip_is_identical_regardless_of_correctness():
    """A real firewall pushes the rule for whatever IP it's given — it
    doesn't know 'correct' from 'wrong' any more than the player does at
    that moment. correct/incorrect is decided elsewhere (apply_verb's own
    matched-IOC lookup); this renderer only ever describes the mechanical
    action, matching the same principle as render_isolate."""
    a = tool_output.render_block_ip("9.9.9.9")
    b = tool_output.render_block_ip("9.9.9.9")
    assert a == b


# ── reset_creds / Active Directory ───────────────────────────────────────────

def test_render_reset_creds_matched_and_unmatched_are_distinct():
    matched = tool_output.render_reset_creds("svc_backup", matched=True)
    unmatched = tool_output.render_reset_creds("not-a-real-account", matched=False)
    assert "disabled" in matched["output"]
    assert "Cannot find" in unmatched["output"]
    assert matched["command"] == "Disable-ADAccount -Identity svc_backup"


# ── isolate / EDR ─────────────────────────────────────────────────────────────

def test_render_isolate_never_renders_a_judgment_on_correctness():
    """See tool_output.py's module docstring: the debrief's collateral
    breakdown and this live action-log entry must never be able to
    contradict each other, which is only guaranteed if this renderer never
    computes its own second opinion. render_isolate takes no on_attack_path
    argument at all — there's nothing for it to leak or contradict."""
    result = tool_output.render_isolate(_HOST_A)
    assert "on_attack_path" not in str(result)
    assert "wrong" not in result["output"].lower()
    assert "correct" not in result["output"].lower()
    assert _HOST_A.hostname in result["output"]


def test_render_isolate_output_identical_for_any_host_state():
    on_path_host = Host(id="host-9", hostname="X", role="server", network_segment_id="s", isolated=False)
    already_isolated_host = Host(id="host-9", hostname="X", role="server", network_segment_id="s", isolated=True)
    assert tool_output.render_isolate(on_path_host) == tool_output.render_isolate(already_isolated_host)


# ── escalate / ServiceNow ─────────────────────────────────────────────────────

def test_render_escalate_is_deterministic_per_seed_and_sequence():
    a = tool_output.render_escalate(seed=11, sequence_number=2)
    b = tool_output.render_escalate(seed=11, sequence_number=2)
    assert a == b


def test_render_escalate_ticket_varies_by_sequence_number():
    a = tool_output.render_escalate(seed=11, sequence_number=0)
    b = tool_output.render_escalate(seed=11, sequence_number=1)
    assert a["output"] != b["output"]
