"""Live Arena Mode: the Org Simulation Engine.

Phase A placeholder — only the archetype constant lives here for now.
Phase B builds `generate_org_state`, `apply_attacker_action`,
`apply_defender_action`, and `replay` on top of this, per
docs/plans/live-arena-mode.md.

`ArenaOrgArchetype` defaults to a Python constant (not a DB table) for v1 —
non-engineers don't need to author archetypes yet, and a table can be
introduced later without touching ArenaMatch/ArenaAction, since matches only
reference archetypes by string key (`ArenaMatch.archetype_key`).
"""

# Placeholder archetypes for Phase B's generate_org_state(seed, archetype) to
# consume. Keep the vocabulary consistent with the existing
# Scenario.industry_vertical / difficulty fields so arena mode reuses the
# same industry/difficulty language as the authored scenario library.
ORG_ARCHETYPES: dict[str, dict] = {
    "small_healthcare": {
        "industry_vertical": "healthcare",
        "difficulty": "beginner",
        "size": "small",
        "host_count_range": [8, 10],
        "segment_count_range": [2, 2],
        "security_maturity": "low",
    },
    "energy_utility": {
        "industry_vertical": "energy",
        "difficulty": "advanced",
        "size": "large",
        "host_count_range": [12, 15],
        "segment_count_range": [3, 3],
        "security_maturity": "medium",
    },
}
