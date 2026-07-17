# Phase 2 State — Action Console Core Loop

Source of truth: `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` section 4 and
`docs/PHASE2_KICKOFF.md`. **Update this file in every item PR** — it's
the record of what's done and what's next, read by hand now rather than
by an automated dispatcher.

**Item kickoff is human-initiated, not automated** — `claude-dispatch.yml`
(which used to auto-start the next item on PR merge) has been removed.
It went 0 for 2 (Items 4 and 5 both merged with it silently pushing
nothing, no error), and both those items needed a real design call
before any code — exactly what a blind dispatch agent can't safely make.
See `REVIEW_CRITERIA.md` (l) for the full reasoning. The reviewer
(`claude-review.yml`) and the `@claude` auto-fix mention (`claude.yml`)
are unaffected and still run automatically on every PR/comment.

Branch: `phase-2-action-console`, off `main` (Phase 1 merged at `ee4a57b`).
Every item lands on its own branch, PR'd into `phase-2-action-console`.
**Item PRs branch from `phase-2-action-console`, not `main`** — the
runner/action's base branch must be set accordingly
(`.github/workflows/claude.yml`'s `base_branch` input, or the equivalent
for whatever triggers the work). `main` does not have Items 0–4 yet and
won't until Phase 2 fully merges — a run cut from `main` has none of the
foundation Item 5+ builds on and cannot produce a PR that merges cleanly
into `phase-2-action-console`. (Found the hard way in issue #3: a cold
cloud-runner run correctly refused to reimplement Items 0–3 from scratch
rather than open a divergent PR, and flagged the base branch as the fix.)

## Status: Items 0–5 complete.

### Completed

- **Compiler** (`115030b`) — `backend/app/services/action_engine.py`:
  `compile_scenario(scenario, seed)` → deterministic `CompiledRun` (hidden
  world state via `org_simulation.generate_org_state`, stage timeline, IOC
  placement, map edges).
- **Item 0 — QA fixes** (`f0e4fcf`) — `is_final` resolved by max
  `trigger_seconds`, not array position; IOC `raw_log` rewritten to the
  bound synthesized host so revealed evidence never contradicts the map.
- **Item 1 — verb application layer** (`3424546`, fixed in `9b760a7`) —
  `backend/app/services/verb_engine.py`: all 8 spec verbs at exact costs,
  `escalate` one-time with a permanent 60s attacker-clock offset, `isolate`
  provably blocks stage compromise, a leak test. `9b760a7` fixed a real
  discoverability bug: `block_ip`'s answer must be extractable from a
  revealed `raw_log`, not just known server-side via `matches_on` — see
  REVIEW_CRITERIA.md (e).
- **Item 2 — `action_runs` table** (`49c88d4`, `total_score` column added
  in `d98cbd0`) — migration `0029_action_runs`, chained off
  `0028_teaser_events`. Round-trip tested against SQLite via stamp-then-
  step (not full-history replay — see the migration test for why).
- **Prep — outcome/scoring** (`d98cbd0`) — `verb_engine.determine_outcome`
  / `compute_score` / `is_run_over`, pure functions.
- **Item 3 — RunState store + WebSocket wiring** (`c976567`, `b9d1f72`) —
  `action_run_store.py` (live `RunState` lifecycle: start/get/apply_verb/
  finalize/sweep_expired), `action_run_ws_handler` on `/ws/run/{run_id}`,
  fully isolated from `simulation_ws_handler`/org tabletop (see
  `tests/test_org_tabletop_regression.py`). `run.end` persists
  `ActionRun`, awards XP (`source_type="action_run"`), and calls
  `check_scenario_achievements` — previously uncalled anywhere in the
  backend — verified live (not just asserted) to unlock `perfect_analyst`/
  `speed_demon` on a realistic play sequence.

Full backend suite: 422 passed, zero regressions, as of `b9d1f72`.

- **Reconnect gap found + fixed during Item 5 planning** — `run.resync`
  (`build_run_resync_event`) sent only clocks
  (`elapsed_seconds`/`attacker_clock_seconds`/`cap_seconds`), never the
  player's earned world state. A reconnecting player — the exact case
  Item 3's resume-by-`run_id` support exists for — got clocks and an
  empty map, losing every revealed host/IOC. Fixed as part of Item 5
  (needed before the frontend could deliver a real "resume this run"
  experience): `verb_engine.earned_state_snapshot` +
  `_revealed_edges` reconstruct exactly what a player has earned
  (`revealed_host_ids`/`discovered_ioc_keys` filtered, same fog-of-war
  gating `apply_verb` already enforces per-delta), threaded through
  `build_run_resync_event`'s new `hosts`/`revealed_iocs`/`edges` fields.
  `scan_network`'s own delta also gained an `edges` key (topology among
  the hosts it just revealed) — `CompiledRun.edges` existed since the
  compiler but was never wired to any client-facing payload before this.
  Two new tests in `test_action_run_ws_handler.py`: a leak test (fresh
  run resyncs to nothing) and an earned-subset test (scan + query_logs on
  one host resyncs to every host but only that host's IOCs).

- **Item 4 — Daily Breach action mode** (`d942266`, migration 0030 in
  `ca4191a`) — `backend/app/api/routes/daily.py`: `_deterministic_daily_seed`
  (SHA-256 of challenge_date+scenario_id, mirroring
  `action_engine._derive_rng`'s style — same scenario+seed for every
  player on a given calendar day, not `secrets.randbelow`), `POST
  /daily/action-run` (409s on a repeat attempt the same day, enforced by
  both a pre-check and migration 0030's DB-level
  `uq_action_run_daily_challenge_user`, mirroring `/attempt`'s existing
  `uq_daily_attempt_user` pattern), `GET
  /daily/action-leaderboard/{id}` (ranked by `action_runs.total_score`,
  a real indexed integer, never `score_breakdown`). `action_run_store`'s
  `LiveRun`/`start_run`/`finalize` now carry an optional
  `daily_challenge_id` through to the persisted `ActionRun` row. The
  8-minute cap fires mid-loop inside a single WS session (verified by
  `test_daily_mode_cap_force_ends_the_run_mid_loop_not_via_final_stage`,
  not just via the separate abandonment sweep). `run.end` carry-over
  (`record_daily_action_run_result`, called from `action_run_ws_handler`
  for mode="daily" runs) updates `DailyChallenge.total_attempts`/
  `avg_score` and `UserStreak` via the existing idempotent-per-day
  `_get_or_create_streak`/`_update_streak`, using the same
  rank/current_streak/longest_streak/total_dailies_played field names
  the decision-gate path's response already uses. The old decision-gate
  quiz path (`/today`, `/scenario/{id}`, `/attempt`, `/leaderboard/{id}`,
  `/streak`, `/history`) is untouched — new challenge generation just no
  longer funnels through it, per REVIEW_CRITERIA.md's org-tabletop
  isolation rule (d).

Full backend suite: 439 passed, zero regressions, as of `d942266`
(also fixed a pre-existing flaky test in `test_scenarios_recent.py`
exposed by this item's new AsyncSessionLocal-based tests — see that
commit).

## Item 5 — Frontend

The automated dispatch agent that was supposed to build this ran 48 turns
against a genuinely fresh, correctly-triggered dispatch and produced no
branch/commit/PR at all — silently incomplete, not crashed, with no error
in the run logs. Not retried blind; built directly instead. (Separately,
the same dispatch agent produced nothing at all on a prior trigger too —
0 for 2. Needs a hard-failure mode, or removal from the loop, before
Phase 3.)

- `frontend/src/lib/useRunSocket.ts` — WS hook for `/ws/run/{run_id}`,
  mirrors `useArenaSocket.ts`'s self-contained-state pattern. Merges every
  verb's `state.delta` shape client-side (distinguished by which keys are
  present, matching `apply_verb`'s own branches), plus `stage.advance`'s
  `newly_compromised_hosts` — only merged into a host already revealed to
  this player, so a stage firing on an unrevealed host stays invisible
  until earned, same fog-of-war contract as every backend delta.
- `frontend/src/components/ActionConsole.tsx` — 8 verb chips + cost
  labels, mobile-first bottom bar (no desktop command-line alternative in
  this version — greenfield layout, no existing bottom-sheet/action-bar
  convention existed in this codebase to match). Targets: no-target verbs
  submit immediately, host-target verbs enter a "tap a host on the map"
  mode (reusing Phase 1's `NetworkMap.tsx` unmodified — client-side
  layout only, grouped by `network_segment_id`, since the backend gives
  topology but no coordinates), free-text verbs (`block_ip`'s IP,
  `reset_creds`'s username — neither is a host id) get an inline text
  input. Host detail drawer shows earned IOCs/forensics/credentials per
  host. Clock UI: `bleed`-colored stage-progress bar. Inline debrief on
  `run.end` (outcome, score breakdown, `XPToast` reuse) — no separate
  debrief page needed.
- **Routing**: individual/solo scenario launches get a brand-new page +
  route (`frontend/src/pages/ActionConsolePage.tsx` at `/run/:runId`),
  NOT a branch inside `SimulationRoomPage.tsx` — mirrors Arena mode's own
  precedent (`ArenaMatchPage.tsx` is its own page for its own WS system)
  and keeps REVIEW_CRITERIA.md's isolation rule (d) unambiguous.
  `SimulationRoomPage.tsx` and `simulation_ws_handler` are untouched by
  Item 5. `ScenarioLibraryPage.tsx`'s `launchScenario` — previously the
  only caller that ever created a `mode="solo"` `SimulationSession` — now
  calls `POST /action-runs` and navigates to `/run/{run_id}` instead;
  this alone delivers "Compressed Run (10 min) as the default mode for
  individual users" without touching the tabletop page, since
  `POST /action-runs` already returns `mode: "scenario"` /
  `cap_seconds: 600`.
- `DailyBreachPage.tsx` — gameplay section reworked to `ActionConsole`;
  `handleStartGame` now calls `POST /daily/action-run` instead of
  fetching decision-gate scenario content. `ResultsPanel` (legacy
  decision-gate shape) is untouched and still renders for a pre-rework
  `DailyAttempt` row; a new `ActionResultsPanel` handles the
  `RunEndSummary` shape action-mode runs actually produce — kept
  separate rather than forcing both scoring models through one component.
  Streak/leaderboard chrome (`StreakBadge`, `CountdownClock`,
  `DailyDrillSection`) unchanged; a new `GET /daily/action-leaderboard`
  query feeds the new results panel (action mode's own scale, never
  mixed with the decision-gate leaderboard).
- Fog of war: before `scan_network`, `hosts` is empty and the map is
  empty — that void IS the fog (not a `NetworkMap.tsx` rendering mode).
  This is honest to what `scan_network` actually earns today but is a
  flatter opening than the spec's "dim/unknown" language implies — logged
  to `docs/BACKLOG.md` for the Phase 5 tone pass rather than changed here
  (changing what `scan_network` earns is a gameplay-balance decision, not
  a UI one).
- **No frontend test runner exists in this repo** (`package.json` has no
  `test` script) — `claude-review.yml`'s automated reviewer only ever
  runs the backend suite, so it is structurally blind to this PR's actual
  frontend content; a green backend suite here is not evidence this UI
  works. Verified manually instead (dev server, full solo + Daily Breach
  play-throughs, mobile viewport, mid-run reconnect). Logged to
  `docs/BACKLOG.md`: add a minimal vitest setup before Phase 3–5 land
  more frontend work.

**Follow-up (post-merge, found by PR #8's own review, independently
confirmed) — `block_ip`/resync asymmetry fixed.** A correct `block_ip`
adds its matched IOC to `discovered_ioc_keys` (so any later resync's
`earned_state_snapshot` already includes its full body), but the LIVE
delta only ever sent `{"correct": True, "host_id": ...}` — a reconnecting
player would see IOC content the live delta never actually showed them.
Confirmed not a leak (the key is genuinely earned the instant the
correct IP is blocked); fixed for parity instead of just documenting the
gap — `block_ip`'s delta now includes the same `revealed_iocs` entry a
resync would, and `useRunSocket.ts`'s delta merge was reordered to
handle that combined shape (it was about to silently drop the isolation
update by falling into the generic `revealed_iocs` branch first). New
test asserts live and resync content are identical, not just that
content exists somewhere.

## After Item 5

- **AppShell mobile pass** (PR #11, merged) — the shared authenticated-page
  sidebar now collapses into a hamburger-triggered slide-in drawer below
  `md:`, unchanged at `md:`+. Blocked the phone-one-thumb acceptance
  criterion; verified via Playwright at 390px and 1280px. `docs/BACKLOG.md`'s
  matching entry marked resolved.
- **Phase 2 acceptance verification — done, see `PHASE2_ACCEPTANCE.md`.**
  8 of 9 spec section 4 criteria PASS with cited evidence (tests, code
  traces, real 390px Playwright browser verification). One real, confirmed
  gap: a player who stays connected and does nothing never loses via the
  natural path — the attacker clock only advances inside verb submission,
  contradicting the spec's own "advances whether or not the player acts"
  design; the abandonment sweep eventually force-ends such a run at 9
  minutes (not ≤8) with an empty narrative. This is an honest, reported gap,
  not silently passed — logged to `docs/BACKLOG.md` as a real-time-tick
  architecture item for before/alongside Phase 3's juice pass. **Phase 2 is
  functionally complete and shippable; this one item should be resolved
  before calling the spec's criterion 3 fully met.**

## Phase 2.5 (queued after Phase 2)

CMMC evidence layer — see `docs/BACKLOG.md`.
