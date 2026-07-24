"""
Standalone analysis script — NOT wired into action_engine.py. Answers one
question before any implementation starts: how many authored hostnames does
each flagship scenario actually name, via three sources (alert_sequence
text, hidden_iocs.matches_on.hostname, hidden_iocs raw_log), and what does a
conservative regex extractor actually pull out vs. miss/over-match.

Run from the backend directory: python harvest_report.py
"""
import re

from seed import COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY

SCENARIOS = [COLONIAL_PIPELINE, SOLARWINDS, MGM_GRAND, LOG4SHELL, NHS_WANNACRY]

# Known rule_id / ticket / CVE / directive shapes that the ALL-CAPS pattern
# below can false-positive on — excluded explicitly since they share the
# same WORD-WORD-NUMBER shape as a real hostname. Residual imprecision:
# this is a per-scenario denylist, not a structural fix — flagged in the
# report output, not hidden.
KNOWN_NON_HOST_IDS = {
    "MS17-010", "ED-21-01", "CHG-4471", "INC-8821", "PMS-08831",
    "DEPLOY-1921", "MW-8811", "HELP-29901", "EMP-4471", "FW-OT-IT-001",
}

# Username shape: single initial + '.' + surname, optionally with trailing
# digits (d.park, j.wright, t.bourne2021) — excluded so the extractor
# doesn't confuse an authored person with an authored host.
USERNAME_RE = re.compile(r"^[a-z]\.[a-z]+\d*$")

# Process/file names by extension — never a host.
FILE_EXTENSIONS = (".exe", ".bin", ".txt", ".tmp", ".class", ".dll", ".b64")

HOSTNAME_PATTERNS = [
    # FQDN-style, restricted to the ".internal" suffix convention every
    # authored internal hostname in these 5 scenarios actually uses
    # (corp.internal / prod.internal / colpipe.internal) — this is what
    # structurally excludes every external/vendor domain (mgmresorts.com,
    # okta.com, proton.me, barnet.nhs.uk, avsvmcloud.com) without needing
    # a growing denylist of external infrastructure.
    re.compile(r"\b[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)*\.internal\b"),
    # bare lowercase word-word-digits (orion-mgmt-01, app-svr-07)
    re.compile(r"\b[a-z]+-[a-z]+-\d{1,3}\b"),
    # ALL-CAPS corporate convention, 2-4 hyphenated segments, ending in digits
    # (CORP-DC-01, NHS-DOMAIN-CTRL-01, FIN-SVR-04, OT-HISTORIAN-01, WKS-ONCO-04)
    re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+){1,3}-\d{1,3}\b"),
]


def harvest_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in HOSTNAME_PATTERNS:
        for m in pattern.findall(text):
            if m in KNOWN_NON_HOST_IDS:
                continue
            if USERNAME_RE.match(m):
                continue
            if m.endswith(FILE_EXTENSIONS):
                continue
            found.add(m)
    # Drop anything that's a proper substring of a longer harvested match
    # (e.g. bare "corp.internal" once "adfs-01.corp.internal" is also
    # present) — keep only maximal matches.
    return {m for m in found if not any(m != other and m in other for other in found)}


def harvest_scenario(scenario: dict) -> dict:
    alert_text = " ".join(
        f"{a.get('description','')} {a.get('raw_log','')}"
        for a in (scenario.get("alert_sequence") or [])
    )
    ioc_text = " ".join(
        f"{i.get('description','')} {i.get('raw_log','')}"
        for i in (scenario.get("hidden_iocs") or [])
    )

    from_alert_text = harvest_from_text(alert_text)
    from_ioc_text = harvest_from_text(ioc_text)
    from_matches_on = {
        i["matches_on"]["hostname"]
        for i in (scenario.get("hidden_iocs") or [])
        if isinstance(i.get("matches_on"), dict) and "hostname" in i["matches_on"]
    }

    all_harvested = from_alert_text | from_ioc_text | from_matches_on
    # Every matches_on.hostname MUST be in the harvested set — that's the
    # hard requirement (every hidden IOC needs a real host to bind to).
    unresolved_matches_on = from_matches_on - all_harvested

    return {
        "title": scenario["title"],
        "from_alert_text": sorted(from_alert_text),
        "from_ioc_text": sorted(from_ioc_text),
        "from_matches_on": sorted(from_matches_on),
        "all_harvested": sorted(all_harvested),
        "unresolved_matches_on": sorted(unresolved_matches_on),
        "hidden_iocs_total": len(scenario.get("hidden_iocs") or []),
        "hidden_iocs_hostname_keyed": len(from_matches_on),
    }


if __name__ == "__main__":
    for scenario in SCENARIOS:
        r = harvest_scenario(scenario)
        print(f"=== {r['title']} ===")
        print(f"  hidden_iocs total: {r['hidden_iocs_total']}  (hostname-keyed matches_on: {r['hidden_iocs_hostname_keyed']})")
        print(f"  harvested from alert_sequence text: {len(r['from_alert_text'])}  {r['from_alert_text']}")
        print(f"  harvested from hidden_iocs text:     {len(r['from_ioc_text'])}  {r['from_ioc_text']}")
        print(f"  matches_on.hostname (structured):    {len(r['from_matches_on'])}  {r['from_matches_on']}")
        print(f"  TOTAL unique harvested hosts:         {len(r['all_harvested'])}")
        if r["unresolved_matches_on"]:
            print(f"  !! UNRESOLVED matches_on.hostname (not harvested by text regex): {r['unresolved_matches_on']}")
        print()
