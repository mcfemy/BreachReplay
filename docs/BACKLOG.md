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

## Fog-of-war tone pass (Phase 5)

Found during Item 5 planning. PHASE2_STATE.md's Item 5 line says
"unexamined hosts render dim/unknown" — Item 5 implements this as
literally as `scan_network` allows: before that verb, the map is empty
(no host exists to the client at all, not even dimmed), and one tap
reveals every host at once. That's an honest reflection of what
`scan_network`'s delta actually earns today, but it means every run opens
identically — an empty map, then one forced tap, a 45s tax on a
non-choice rather than a real fog-of-war decision. A real SOC team
already knows its own topology; the interesting fog is *compromise
state*, not *host existence*. Revisiting this means changing what
`scan_network` (and possibly a cheaper/free initial reveal) actually
earns in `verb_engine.py` — that's a gameplay-balance decision, not a UI
one, and explicitly out of scope for Item 5. Revisit alongside Phase 5's
broader tone pass.

## Frontend test coverage — no runner configured

The frontend (`frontend/`) has no test runner at all (`package.json` has
no `test` script, no vitest/jest, confirmed while scoping Item 5). This
means `claude-review.yml`'s automated reviewer — which only ever runs
`cd backend && pytest -q` — is structurally blind to every frontend PR's
actual UI/logic content; a green backend suite says nothing about whether
a frontend change works. Item 5's own PR is the first real casualty of
this (a large, genuinely new UI with zero automated coverage, verified
only by manual play-through). Add a minimal vitest + React Testing
Library setup before Phase 3-5 land more frontend work, so those PRs stop
being reviewed blind.

## AppShell's sidebar doesn't collapse on mobile — blocks phone playability

Found while verifying Item 5's mobile-first requirement in a real 390px
viewport (Playwright, iPhone-sized). `frontend/src/components/AppShell.tsx`
— the shared layout wrapper every authenticated page renders inside,
including the new `ActionConsole` — has no responsive behavior at all: its
full nav sidebar (Scenarios/Daily Breach/Red Team/Arena/Leaderboard/Teams/
Org Upload/My Certs) stays permanently visible and takes roughly HALF the
viewport width on a phone, squeezing everything else — including Item 5's
own verb-chip bar and network map — into a cramped ~180px column with
wrapping button labels. Confirmed via the same earlier frontend survey
that found zero responsive breakpoints anywhere in the codebase (`sm:`/
`md:`/`lg:` prefixes, a collapsible-sidebar pattern) — this is not
something Item 5 introduced or made worse; `ActionConsole`'s own layout
(verb chips, map, drawer) is genuinely mobile-first as built, it's
AppShell's chrome around it that isn't.

This matters beyond a nitpick: PHASE2_STATE.md's "After Item 5" Phase 2
acceptance checklist explicitly requires "phone-with-one-thumb
playability" before declaring Phase 2 done — that gate cannot pass while
AppShell doesn't collapse. Fixing it (a collapsible/hamburger sidebar
below some breakpoint) touches shared chrome used by every authenticated
page, not just the new action console, so it's deliberately left out of
Item 5's own PR rather than rushed in at the end of an already large
change — but it needs a real pass before Phase 2's acceptance
verification, not after.

## GET /daily/today's already_played/my_attempt don't see ActionRun completions

Found while reworking `DailyBreachPage.tsx` for Item 5. `GET /daily/today`
(`backend/app/api/routes/daily.py`) derives `already_played`/`my_attempt`
from the `DailyAttempt` table only — the old decision-gate quiz's own
table. A player who completes today's challenge through the new
action-console path (`ActionRun`, `mode="daily"`) gets no `DailyAttempt`
row, so a page reload after playing shows the lobby again instead of
their results. This does NOT reopen the double-play hole — `POST
/daily/action-run`'s own three-layer check (persisted-row pre-check,
live-run lookup, DB constraint) still correctly blocks/resumes a repeat
attempt — it's purely a "lost my results view on refresh" UX gap.
Fixing it means teaching `/daily/today` to also check `ActionRun` for
today's challenge; deferred out of Item 5's frontend-rework scope.
