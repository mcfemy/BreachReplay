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

## Daily-challenge picker can select synthetic/test-titled scenarios — prod-safety, not just test hygiene

Found while chasing an unrelated `compression_ratio` bug (action_engine.py
gate-timing fix): `_get_or_create_daily_challenge`
(`backend/app/api/routes/daily.py`) picks a random `status="approved"`
scenario for the day, with no notion of "real content" vs "test
fixture" — it trusts `status` alone. Several tests
(`test_daily_action_mode.py`, `test_action_run_ws_handler.py`) create
`Scenario` rows with `status="approved"` and commit them for real via
`app.db.session.AsyncSessionLocal` directly, bypassing the `db` fixture's
rolled-back transaction, because `action_run_store.finalize()` opens its
own session — a different connection than the test's, so writes made only
through the rolled-back `db` fixture would be invisible to it (documented
in `test_daily_action_mode.py`'s module docstring). Confirmed live: a
scenario titled "Daily Action Mode Test Scenario" — left behind by a prior
test run against the shared dev DB — was the scenario actually backing a
real Daily Breach challenge in this environment.

Two fixes worth considering, not mutually exclusive:
  1. The picker should exclude non-production scenarios via a real flag on
     `Scenario` (e.g. `is_test_fixture` or similar), not a title-string
     match — a title match is exactly the kind of check that silently stops
     working the moment someone names a test fixture something ordinary.
  2. These tests should run against an isolated test database instead of
     the shared dev DB, so a failed/aborted test run can't leave `approved`
     rows behind for the real app to find at all.

Not bundled into the `compression_ratio` fix because it's an orthogonal,
pre-existing latent bug (present before that work and unrelated to it) —
but it's a real prod-safety gap, not merely test-suite flakiness, since it
can put synthetic content in front of an actual player.

## Hidden IOCs have no discoverable correlation to the visible alert feed

Found while manually verifying the `hidden_iocs` backfill deploy against a
real production Daily Breach run. `_build_stages`
(`backend/app/services/action_engine.py`) already says this out loud in its
own docstring: the attack path is "built via a seeded RNG, since the
scenario's own free-text hostnames (e.g. 'CORP-DC-01') don't correspond to
synthesized host ids and have no reliable mapping to them." Confirmed live:
reproduced the exact deterministic placement for a real prod run (SolarWinds,
seed `1341145589`) — the 3 hidden IOCs landed on `host-6`/`host-5`/`host-2`,
while the player's visible alert feed (`alert_lines`, delivered verbatim from
the scenario's authored `alert_sequence`) referenced the original static
hostnames (`orion-mgmt-01`, `adfs-01.corp.internal`, etc.), which have zero
relationship to those synthesized map node ids.

`hidden_iocs`' own docstring (`backend/seed.py`) frames the mechanic as
rewarding a player who "pivots the investigation panel on the right
field/value" — i.e., notices a value in one alert and follows it up
elsewhere. That correlation is impossible today: the only visible signal a
host is worth investigating is `compromise_level` (red/pulsing on the map),
which just means "some decision-gate stage compromised this host at some
point," not "this specific host holds evidence." With several hosts
typically compromised over a run and only a handful of hidden IOCs (3 for
SolarWinds), a player currently has no better strategy than querying every
compromised host and hoping — confirmed by an actual live play-through
during this deploy, where 2 of 5 queried compromised hosts came up empty
before the 3rd hit.

Not fixed here — this is a design/gameplay question, not a bug with an
obvious one-line fix. Worth considering, not mutually exclusive: (1) rewrite
`alert_sequence` entries the same way `_rewrite_raw_log_for_host` already
rewrites `hidden_iocs`' `raw_log`, so the visible feed's hostname mentions
genuinely point at real map nodes; (2) a real-time visual cue (a distinct
highlight/pulse) on the exact host a decision-gate stage compromises at the
moment it fires, teaching the player by watching rather than reading; (3)
something else entirely. Revisit alongside Phase 5's broader tone pass (see
the fog-of-war entry above, which is adjacent).

## `user_streaks` idempotency guard doesn't survive same-day test reruns

Found while re-verifying the full backend suite during Phase 2 close-out.
`test_daily_action_mode.py`'s streak/rank tests (`test_daily_run_end_carries_over_streak_and_rank_fields`,
`test_swept_daily_run_broadcasts_run_end_and_carries_over_streak`, and
others sharing the same fixed literal user ids like `daily-cap-owner-1`)
write real `UserStreak` rows via `AsyncSessionLocal` (same non-rolled-back
pattern as the `is_synthetic` finding above). `_update_streak`'s
idempotency guard (`daily.py`) is keyed on `last_played_date == <real
today>` — but rerunning the same test twice on the same real calendar day
(trivially possible during a single active dev session, not a rare edge
case) does not consistently short-circuit: `current_streak` was observed
at `2` instead of the expected `1` after a same-day rerun, failing the
test's own assertion. Worked around during this pass by deleting the
affected `user_streaks` rows before each clean suite run; not fixed here
since it's orthogonal to Phase 2's actual close-out work. Worth either a
session-scoped cleanup fixture for these fixed test user ids (mirroring
the `is_synthetic` fix's spirit — stop the shared-DB writes from being
real in the first place) or tightening `_update_streak`'s guard to be
provably idempotent under a same-day rerun.

## `username`/`process_name`-keyed hidden IOCs have no reveal mechanism at all

Found while specing the host-namespace-unification fix
(`docs/HOST_NAMESPACE_UNIFICATION_SPEC.md`) — this is a distinct, more
severe bug than that spec's own subject, surfaced by the same investigation
but explicitly out of that spec's scope. `verb_engine.py`'s full verb
switch has exactly one value-based IOC pivot: `block_ip`, which matches
`matches_on.get("ip") == target` regardless of which host the IOC physically
landed on. There is no equivalent for `matches_on["username"]` or
`matches_on["process_name"]`. `reset_creds` looks like it should be the
username case — it isn't: it matches against `world.credentials` (a
different data structure) and disables a credential, but never touches
`discovered_ioc_keys` or reveals anything.

Confirmed live: MGM Resorts' scenario has 4 hidden IOCs, 3 of them keyed on
`username` (`CROSSTENANT`) or `process_name` (`RMM`, `BACKUPWIPE`). All 3
are reachable today only by `query_logs`/`image_disk`-ing the exact
(procedurally-named, unguessable) host `_place_iocs` happened to bind them
to — there is no value-based shortcut, unlike the 4th (ip-keyed) IOC, which
`block_ip` already reveals correctly regardless of host confusion. The
host-namespace fix doesn't touch this gap: there's no hostname to harvest
for a username/process_name-keyed entry in the first place.

Not fixed here — needs its own design pass (a `reveal_by_username`-shaped
verb path, or teaching `reset_creds`/a new verb to also check
`ioc_placements` by `matches_on["username"]`/`matches_on["process_name"]`,
mirroring `block_ip`'s pattern). Worth prioritizing: this affects every
scenario whose hidden IOCs lean on account/process signatures rather than
host/IP ones, not just MGM.
