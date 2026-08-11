"""
Diegetic tool output — Action Console.

Feedback from a security-professional tester: the console taught judgment
but hid the tooling. A player tapped SCAN NETWORK, time was spent, a map
appeared, and nothing said what actually ran. This module closes that gap:
every verb, once resolved, gets a realistic rendering of the real tool a
responder would actually be looking at — a command (where the verb maps to
one), and output in that tool's real format.

Three rules, non-negotiable, in priority order:

1. LEAK SAFETY. Every render_* function below takes ONLY the same
   already-filtered values verb_engine.apply_verb's own delta for that verb
   already computed — the target Host, that host's already-filtered
   credentials/revealed_iocs list, the forensics dict, the plain strings a
   player typed themselves. Never `compiled.stages`, never `matches_on`,
   never `mitre_technique`, never an unfired stage, never a host/IOC this
   call didn't already reveal. If a render_* function needed something not
   already sitting in its caller's local variables in apply_verb, that
   would itself be a leak-safety bug — there is no server round-trip here
   to smuggle extra state through.

2. REAL SYNTAX ONLY. Every command/output format below is drawn from a
   real, verifiable tool convention (see each function's docstring for
   which). Two fields are honest synthetic values, not fabricated claims
   about anything real — flagged explicitly, same discipline already
   applied to procedural hostnames elsewhere in this engine:
     - Host IP addresses: Host has no IP field at all (org_simulation.py).
       `_synthetic_ip` derives one deterministically from
       (network_segment_id, host_id) purely for realistic nmap/log output —
       cosmetic only, never stored, never affects scoring.
     - image_disk's SHA256: a real, correctly-formatted hash string,
       deterministically derived from (seed, host_id) — not "the hash of"
       any actual bytes, exactly as honest as this engine's already-
       procedural decoy hostnames.

3. DETERMINISTIC. Same (scenario, seed) + same verb sequence must render
   byte-identical tool output every time — Phase 4 ghost racing depends on
   it. Every render_* function that needs a cosmetic random-looking value
   (an IP octet, a hash, a scan latency, a ticket number) derives it from
   `_derive_rng(seed, salt)`, the same SHA-256-based per-purpose RNG
   derivation action_engine.py/org_simulation.py already establish — never
   real `random`, never wall-clock time.

Consistency with the debrief (Proportionate Response): `render_isolate`
deliberately does NOT restate whether the isolated host was actually on
the attack path — that judgment already exists exactly once, in
`verb_engine._attack_path_host_ids` (which both the live `on_attack_path`
delta field and the post-run collateral breakdown already read from). This
module never computes a second, independent opinion that could drift from
that — it only describes the mechanical EDR action, nothing evaluative.
"""

from __future__ import annotations

import hashlib
import random

from app.services.action_engine import Host, IOCPlacement


def _derive_rng(seed: int, salt: str) -> random.Random:
    """Identical derivation to action_engine._derive_rng / org_simulation.
    _derive_rng — duplicated locally per this codebase's existing
    convention (see action_engine.py's own docstring on why: SHA-256-based,
    avoids CPython's Random(x)/Random(-x) sign-symmetric collision risk)."""
    h = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _synthetic_ip(seed: int, network_segment_id: str, host_id: str) -> str:
    """A stable, private-range (RFC 1918) IP for display purposes only —
    Host carries no real IP field. Same segment always renders the same
    /24; same host_id always renders the same address within it."""
    segment_octet = _derive_rng(seed, f"tool-output-segment-octet:{network_segment_id}").randint(10, 250)
    host_octet = _derive_rng(seed, f"tool-output-host-octet:{host_id}").randint(2, 254)
    return f"10.{segment_octet}.4.{host_octet}"


def _synthetic_hash(seed: int, host_id: str) -> str:
    """A real, correctly-formatted SHA256 hex digest — not the hash of any
    actual bytes (there are none; this is a fictional acquisition), same
    honesty convention as this engine's procedural decoy hostnames."""
    h = hashlib.sha256(f"tool-output-image-hash:{seed}:{host_id}".encode())
    return h.hexdigest()


def _elapsed_clock(elapsed_seconds: int) -> str:
    """HH:MM:SS from the game clock — already player-visible via clock.tick,
    not new information, just formatted for a log-line timestamp column."""
    h, rem = divmod(max(0, elapsed_seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_scan_network(seed: int, hosts: list[Host], elapsed_seconds: int) -> dict:
    """nmap host discovery (-sn: ping scan, no port scan — matches what
    scan_network actually does narratively: find what's alive, not probe
    services). Lists exactly the hosts scan_network's own delta already
    reveals (all of them) — nothing scan_network doesn't already show."""
    if not hosts:
        return {"tool": "nmap", "command": "nmap -sn 10.10.4.0/24", "output": "Nmap done: 0 IP addresses (0 hosts up) scanned in 0.01 seconds"}

    segment_id = hosts[0].network_segment_id
    subnet_octet = _derive_rng(seed, f"tool-output-segment-octet:{segment_id}").randint(10, 250)
    lines = [f"Starting Nmap 7.94 ( https://nmap.org )"]
    for host in sorted(hosts, key=lambda h: h.id):
        ip = _synthetic_ip(seed, host.network_segment_id, host.id)
        latency_rng = _derive_rng(seed, f"tool-output-latency:{host.id}")
        latency = latency_rng.randint(80, 4200) / 100000
        lines.append(f"Nmap scan report for {host.hostname} ({ip})")
        lines.append(f"Host is up ({latency:.4f}s latency).")
    duration = _derive_rng(seed, "tool-output-scan-duration").randint(140, 420) / 100
    lines.append(f"Nmap done: {len(hosts)} IP addresses ({len(hosts)} hosts up) scanned in {duration:.2f} seconds")
    return {
        "tool": "nmap",
        "command": f"nmap -sn 10.{subnet_octet}.4.0/24",
        "output": "\n".join(lines),
    }


def render_query_logs(seed: int, host: Host, revealed_iocs: list[IOCPlacement], elapsed_seconds: int) -> dict:
    """Splunk SPL — the one SIEM convention this feature commits to (the
    scenario content's own "source_system" values are generic ("SIEM"),
    never a specific vendor, so nothing in the authored content contradicts
    picking Splunk here). Results are exactly `revealed_iocs` — this call's
    own already-filtered set, nothing broader."""
    command = f'search index=main host="{host.hostname}" earliest=-24h@h latest=now | table _time, source, signature, message'
    if not revealed_iocs:
        output = "Search complete. 0 results found."
    else:
        rows = ["_time                source           signature       message"]
        for p in revealed_iocs:
            rows.append(f"{_elapsed_clock(elapsed_seconds)}             {p.source_system:<16} {p.rule_id:<15} {p.raw_log}")
        output = "\n".join(rows)
    return {"tool": "Splunk", "command": command, "output": output}


def render_image_disk(
    seed: int, host: Host, revealed_iocs: list[IOCPlacement],
    unpatched_cves: list[str], edr_installed: bool, elapsed_seconds: int,
) -> dict:
    """dd + sha256sum — real, vendor-neutral forensic acquisition syntax
    (not a specific commercial imaging tool's proprietary CLI, which this
    codebase has no way to verify the exact flags of)."""
    image_size_mb = _derive_rng(seed, f"tool-output-image-size:{host.id}").randint(40000, 480000)
    blocks = image_size_mb // 4
    duration = _derive_rng(seed, f"tool-output-image-duration:{host.id}").randint(180, 900)
    digest = _synthetic_hash(seed, host.id)
    command = f"dd if=/dev/sda of=/evidence/{host.hostname}.img bs=4M conv=noerror,sync && sha256sum /evidence/{host.hostname}.img"
    lines = [
        f"{blocks}+0 records in",
        f"{blocks}+0 records out",
        f"{image_size_mb * 1024 * 1024} bytes ({image_size_mb} MB) copied, {duration} s",
        f"{digest}  {host.hostname}.img",
    ]
    if revealed_iocs:
        lines.append("")
        lines.append(f"Live triage — {len(revealed_iocs)} indicator(s) recovered from this image (see log query for detail).")
    lines.append(f"EDR agent: {'present' if edr_installed else 'not detected'}. Unpatched CVEs on record: {len(unpatched_cves)}.")
    return {"tool": "dd / sha256sum", "command": command, "output": "\n".join(lines)}


def render_interview_user(host: Host, credentials: list[dict]) -> dict:
    """Not a tool — interview notes. `credentials` here is the SAME
    already-filtered list interview_user's own delta already sends
    (username/privilege only, already scoped to this host)."""
    if not credentials:
        note = f"No user on record with direct account access to {host.hostname}. Nothing further to add."
    else:
        usernames = ", ".join(c["username"] for c in credentials)
        note = (
            f"User confirms {len(credentials)} account(s) with access to {host.hostname}: {usernames}. "
            "States access is routine for their role; doesn't recall anything unusual recently."
        )
    return {"tool": "Interview Notes", "command": None, "output": note}


def render_block_ip(target: str) -> dict:
    """iptables — echoes back only the IP the player themselves typed,
    regardless of whether it matched a real IOC (a real firewall doesn't
    know that either — it just pushes the rule)."""
    command = f"iptables -A INPUT -s {target} -j DROP"
    output = f"Rule added.\n$ iptables -L INPUT -n | grep {target}\nDROP       all  --  {target}              0.0.0.0/0"
    return {"tool": "iptables", "command": command, "output": output}


def render_reset_creds(target: str, matched: bool) -> dict:
    """Active Directory PowerShell — `matched` is exactly
    (cred_matched is not None or ioc_matched is not None), already computed
    by apply_verb's own reset_creds branch. A real, distinct AD error for
    an account that genuinely doesn't exist vs. a real disable confirmation
    — no new information beyond what `delta["correct"]` already carries."""
    command = f"Disable-ADAccount -Identity {target}"
    if matched:
        output = f"Identity '{target}' disabled. Event 4725 logged (account disabled)."
    else:
        output = f"Disable-ADAccount : Cannot find an object with identity: '{target}'."
    return {"tool": "Active Directory", "command": command, "output": output}


def render_isolate(host: Host) -> dict:
    """EDR containment action-log entry. Deliberately does not restate
    on_attack_path (see this module's own docstring — that judgment lives
    exactly once, in verb_engine._attack_path_host_ids, not duplicated
    here) — purely mechanical, matching what an EDR console actually shows
    the analyst who just clicked "isolate"."""
    output = f"[EDR Console] Isolation policy applied to {host.hostname}. Containment: Full network isolation. Status: Success."
    return {"tool": "EDR", "command": None, "output": output}


def render_escalate(seed: int, sequence_number: int, party_name: str | None) -> dict:
    """ServiceNow-style incident creation — fits the existing content's own
    "Help Desk"/"IT Helpdesk" source_system references. Ticket number is
    deterministic (seed + sequence), not real-random. `party_name` (Phase
    3 — escalate is targeted on a scenario with an authored
    notification_matrix) rides along in the ticket text so the player
    sees confirmation of WHO this notification went to, not just that a
    generic ticket was filed. `None` on a matrix-less scenario's fallback
    path — the exact original pre-Phase-3 text, unchanged, not a
    "Notify: None" regression."""
    ticket = _derive_rng(seed, f"tool-output-ticket:{sequence_number}").randint(100000, 999999)
    if party_name is None:
        output = f"INC{ticket} created. Priority: P1 — Critical. Category: Security Incident. Assigned: SOC Manager (on-call)."
    else:
        output = (
            f"INC{ticket} created. Priority: P1 — Critical. Category: Security Incident. "
            f"Notify: {party_name}. Assigned: SOC Manager (on-call)."
        )
    return {"tool": "ServiceNow", "command": None, "output": output}
