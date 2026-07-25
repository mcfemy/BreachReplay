"""
Playability criterion for the flagship scenarios: any value a hidden_ioc's
matches_on expects a player to submit (block_ip's ip, reset_creds's
username) must actually be readable somewhere in the visible alert feed
before the player needs it — otherwise a value-pivot verb has nothing to
pivot from, and the "read the alert, deduce the answer" premise
(docs/HOST_NAMESPACE_UNIFICATION_SPEC.md) is broken for that IOC
specifically, independent of whether the verb mechanics themselves work.

Pure, synchronous, content-only checks — no compile_scenario/verb_engine
involved, just seed.py's authored dicts. Imports seed.py directly (same
pattern as harvest_report.py) rather than re-deriving fixtures, so this
stays accurate as scenario content evolves.
"""
from seed import COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY

SCENARIOS = [COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY]


def _visible_alert_text(scenario: dict) -> str:
    """Only what a player can actually read pre-discovery: the ambient
    alert_sequence feed. Deliberately excludes hidden_iocs' own
    description/raw_log — those are the hidden evidence itself, not
    something visible before it's earned, so they can't count as the
    "readable content" a value is supposed to be deducible from."""
    return " ".join(
        f"{a.get('description','')} {a.get('raw_log','')}"
        for a in (scenario.get("alert_sequence") or [])
        if isinstance(a, dict)
    )


def test_every_username_keyed_hidden_ioc_value_is_readable_in_the_alert_feed():
    failures = []
    for scenario in SCENARIOS:
        visible = _visible_alert_text(scenario)
        for ioc in scenario.get("hidden_iocs") or []:
            username = (ioc.get("matches_on") or {}).get("username")
            if username and username not in visible:
                failures.append(f"{scenario['title']!r}: {ioc.get('rule_id')!r} expects {username!r}, "
                                 f"not found anywhere in alert_sequence")
    assert not failures, "value-pivot IOC(s) with nothing to pivot from:\n" + "\n".join(failures)


def test_every_ip_keyed_hidden_ioc_value_is_readable_in_the_alert_feed():
    """block_ip already had this property for all 5 flagship scenarios —
    asserted here so it stays true as content evolves, matching the same
    bar the new username test above enforces."""
    failures = []
    for scenario in SCENARIOS:
        visible = _visible_alert_text(scenario)
        for ioc in scenario.get("hidden_iocs") or []:
            ip = (ioc.get("matches_on") or {}).get("ip")
            if ip and ip not in visible:
                failures.append(f"{scenario['title']!r}: {ioc.get('rule_id')!r} expects {ip!r}, "
                                 f"not found anywhere in alert_sequence")
    assert not failures, "value-pivot IOC(s) with nothing to pivot from:\n" + "\n".join(failures)


def test_process_name_keyed_iocs_are_the_documented_gap_not_silently_pivotable():
    """Not a bug assertion — a tripwire. process_name-keyed IOCs have no
    reveal-by-value verb at all (docs/BACKLOG.md), so whether their value
    is readable in the alert feed is currently moot. If a future verb adds
    process_name pivoting, this test should be extended to match the
    username/ip tests above rather than left silent."""
    process_name_iocs = [
        (s["title"], ioc.get("rule_id"))
        for s in SCENARIOS
        for ioc in (s.get("hidden_iocs") or [])
        if (ioc.get("matches_on") or {}).get("process_name")
    ]
    assert process_name_iocs, "expected at least one process_name-keyed IOC to exist (MGM's RMM/BACKUPWIPE) — if this is now empty, the gap may already be closed and this test/BACKLOG.md should be updated"
