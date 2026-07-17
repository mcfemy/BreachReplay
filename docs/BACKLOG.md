# Backlog

Items identified during active work that are real but explicitly out of
scope for the phase/item in progress when they were found. Not a general
issue tracker — just the small set of things flagged mid-work worth not
losing.

## Phase 2.5 — CMMC evidence layer (queued after Phase 2)

Follows the full game-overhaul Phase 2 (action console core loop). Not yet
scoped in detail; queued here as a placeholder so it isn't lost between
Phase 2's completion and its own kickoff. Revisit
`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` and this project's compliance-
evidence-export precedent (`GET /admin/compliance-analytics`,
`compliance_evidence` fields on `SimulationSession.debrief_report`) as the
starting point for what a CMMC-flavored evidence layer needs to add on top
of what Phase 2's `ActionRun`/`action_log` already captures.

## Decision-gate scenario completion never awards XP or checks achievements

Found during Phase 2 Item 3 research (confirmed via repo-wide search):
`xp_service.check_scenario_achievements` — which already implements
`first_blood`, `perfect_analyst`, `speed_demon`, `scenario_5`,
`scenario_10`, and the per-scenario title badges — has **zero callers**
anywhere in the backend on the old (decision-gate) completion path.
Neither `POST /sessions/{id}/complete`
(`backend/app/api/routes/sessions.py`) nor the debrief Celery task
(`generate_session_debrief` / `_generate_debrief_sync` in
`backend/app/pipeline/tasks.py`) calls `award_xp` or
`check_scenario_achievements`. A user who completes a full org-tabletop or
solo decision-gate scenario today earns no XP and unlocks no scenario
achievement at all — the achievement catalogue and checking logic exist
and are correct, they're just never invoked.

Phase 2 Item 3 wires exactly this pattern in for action-mode runs
(`action_run_store.finalize`, `source_type="action_run"`) — `verb_engine`/
`action_run_store` were the first real callers of
`check_scenario_achievements` in the codebase. The decision-gate path's
gap is pre-existing and untouched by Phase 2 (per the org-tabletop
isolation rule — see `REVIEW_CRITERIA.md`); fixing it is a separate,
future change, not bundled into Phase 2 item work.

## `POST /learning/knowledge-check/{id}/attempt` has no re-submission guard

Found while fixing the Daily Drill "Next repeats the same question" bug
(`backend/app/api/routes/learning.py`). Structurally the same shape as the
`/teaser/answer` bug documented in
`docs/PHASE1_ANSWER_IDEMPOTENCY_HANDOFF.md` — a mutation endpoint with no
guard against being called more than once for the same logical action — but
NOT the cause of the Daily Drill bug (that was `get_next_knowledge_check`
never excluding a just-answered question; fixed separately) and not
currently harmful: a repo-wide search confirms `UserKnowledgeCheckAttempt`
rows are written here and never read anywhere else in the backend, so a
duplicate submission today has no observable effect on score, mastery, or
any metric. Unlike teaser (a one-time landing-page decision), this endpoint
is legitimately re-answerable by design — spaced repetition means the same
question should be able to resurface and be re-attempted on a later day — so
a blind "first-answer-wins forever" guard (teaser's fix) would be actively
wrong here. If this table ever grows a real reader (e.g. drill attempts
start feeding `mastery_service` — see the fix commit's docstring for why
they currently don't), revisit with a debounce-style guard scoped to a short
time window instead.
