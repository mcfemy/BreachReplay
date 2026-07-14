"""
Static, hand-curated payload for the no-auth landing teaser (Phase 1,
BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 3).

Deliberately NOT derived live from the `scenarios` table at request time:
the teaser must never be able to leak `hidden_iocs`, `decision_tree`
rationale, or any other full-scenario field, so its payload is a hand-picked
subset adapted from the real Colonial Pipeline scenario in
`backend/seed.py`'s `COLONIAL_PIPELINE` dict — the +0m..+16m alert_sequence
entries, and gate-004's real lesson (isolate the lateral-movement *source*,
not the destinations one at a time) — kept as a plain constant here rather
than a DB read.

`TEASER_CORRECT_NODE_ID` is intentionally never sent to the client; only
`app/api/routes/teaser.py`'s /teaser/answer handler reads it.
"""

SCENARIO_KEY = "colonial_pipeline_teaser_v1"

HEADLINE = "This breach really happened. It took them 6 days to contain it. You have 60 seconds."

COUNTDOWN_SECONDS = 60

# 8 nodes, laid out for a small SVG topology (see frontend/src/components/NetworkMap.tsx).
NODES = [
    {"id": "VPN-GW-01", "label": "VPN-GW-01", "x": 60, "y": 200},
    {"id": "MAIL-01", "label": "MAIL-01", "x": 200, "y": 100},
    {"id": "WEB-02", "label": "WEB-02", "x": 200, "y": 300},
    {"id": "WKS-22", "label": "WKS-22", "x": 340, "y": 60},
    {"id": "DC-01", "label": "DC-01", "x": 340, "y": 200},
    {"id": "FIN-03", "label": "FIN-03", "x": 480, "y": 140},
    {"id": "HISTORIAN-01", "label": "HISTORIAN-01", "x": 480, "y": 260},
    {"id": "BACKUP-01", "label": "BACKUP-01", "x": 340, "y": 340},
]

EDGES = [
    {"source": "VPN-GW-01", "target": "MAIL-01"},
    {"source": "VPN-GW-01", "target": "WEB-02"},
    {"source": "MAIL-01", "target": "WKS-22"},
    {"source": "MAIL-01", "target": "DC-01"},
    {"source": "DC-01", "target": "FIN-03"},
    {"source": "DC-01", "target": "HISTORIAN-01"},
    {"source": "DC-01", "target": "BACKUP-01"},
]

# MAIL-01 is already compromised (phished) when the teaser opens — the "one
# node already pulsing red" from the player-experience spec.
INITIAL_NODE_STATES = {"MAIL-01": "pulsing"}

# Condensed from COLONIAL_PIPELINE["alert_sequence"] (+0m..+16m), reworded to
# point at MAIL-01 instead of the real scenario's CORP-WKS-22/CORP-DC-01
# hostnames so it matches this teaser's smaller topology.
ALERT_LINES = [
    {"timestamp": "+0m", "text": "VPN login from 185.220.101.34 — account: svc_backup — geo: RU"},
    {"timestamp": "+4m", "text": "Encoded PowerShell on MAIL-01 — parent: outlook.exe"},
    {"timestamp": "+8m", "text": "CRITICAL — credential dump detected on DC-01 (lsass.exe)"},
    {"timestamp": "+12m", "text": "New domain admin 'svc_update01' — no ticket on file"},
    {"timestamp": "+16m", "text": "Lateral movement: RDP sessions opening from MAIL-01 toward 3 hosts"},
]

# The map itself is the input: only these 3 nodes are clickable.
DECISION = {
    "id": "teaser-gate-001",
    "trigger_alert": "Lateral movement detected from MAIL-01. Isolate which host?",
    "node_choices": ["MAIL-01", "DC-01", "FIN-03"],
}

TEASER_CORRECT_NODE_ID = "MAIL-01"

CONSEQUENCE_CORRECT = (
    "Isolating the source stops it cold. MAIL-01 is contained before the lateral "
    "movement can spread any further."
)
CONSEQUENCE_WRONG_BLEED_NODES = ["DC-01", "FIN-03"]
CONSEQUENCE_WRONG = (
    "Wrong host. The infection keeps spreading through MAIL-01 — DC-01 and FIN-03 "
    "are compromised. FIN-03 encrypted."
)

END_CARD_TEXT = (
    "That was step 1 of 7 in the real Colonial Pipeline attack. The real team "
    "missed it. Play the full breach free."
)
