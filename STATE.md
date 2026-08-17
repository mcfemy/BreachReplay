# Project State

Source of truth for what's shipped and what's next, read by hand — not by
an automated dispatcher. **Update this file at the end of each phase**
(not per-item; per-item detail lives in that phase's own commits/PRs) so
the next phase starts from an accurate picture without anyone having to
dig through history first.

**Durable convention, so a phase boundary needs no workflow edits:** every
phase's work happens on its own branch cut from `main`
(`phase-N-<short-name>`), and merges back into `main` directly once the
phase's acceptance doc (`<PHASE>_ACCEPTANCE.md` at the repo root — see
`PHASE2_ACCEPTANCE.md` for the pattern) confirms it's done.
`.github/workflows/claude.yml`'s `base_branch` always points at `main`,
never at a specific phase branch — Phase 2 briefly hardcoded it to
`phase-2-action-console` while that branch was the only place Items 0+
existed, which meant every dispatched run had to target that one branch
by name and would have needed a manual workflow edit at every phase
boundary. Now that each phase merges to `main` promptly instead of
staying a long-lived integration branch, `main` is always current and
always the right base — no workflow file should ever again need to
change just because a phase finished.

**Item kickoff is human-initiated, not automated** — `claude-dispatch.yml`
(which used to auto-start the next item on PR merge) was removed during
Phase 2. It went 0 for 2 (two items both merged with it silently pushing
nothing, no error), and both needed a real design call before any code —
exactly what a blind dispatch agent can't safely make. See
`REVIEW_CRITERIA.md` (l) for the full reasoning. The reviewer
(`claude-review.yml`) and the `@claude` auto-fix mention (`claude.yml`)
are unaffected by this and still run automatically on every PR/comment,
including on future phases — those two workflows were never phase-specific.

---

## Phase 2 — Action Console Core Loop (complete — merged to `main` via PR #21, `08d0674`)

Everything in this section is historical record from when this phase was
active — kept for context on how its design decisions were made, not
current state. Source of truth while it was in flight:
`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` section 4 and
`docs/PHASE2_KICKOFF.md`. Final acceptance verification lives in
`PHASE2_ACCEPTANCE.md` — all 9 of spec section 4's criteria re-verified
against the code as merged, 9/9 PASS (criterion 3 rewritten — the
original wording assumed a real-time clock, incoherent against this
engine's actual turn-based spend-clock design; see that doc).

Branch: `phase-2-action-console`, off `main` (Phase 1 merged at `ee4a57b`).
Every item landed on its own branch, PR'd into `phase-2-action-console`.
**Item PRs branched from `phase-2-action-console`, not `main`** while this
phase was active — `main` didn't have Items 0–4 until Phase 2 fully
merged, so a run cut from `main` had none of the foundation Item 5+ built
on and couldn't produce a PR that merged cleanly into
`phase-2-action-console`. (Found the hard way in issue #3: a cold
cloud-runner run correctly refused to reimplement Items 0–3 from scratch
rather than open a divergent PR, and flagged the base branch as the fix.)
This is exactly the class of per-phase workflow friction the durable
convention above now avoids for future phases.

### Status: Items 0–5 complete, phase merged.

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
  quiz PLAY path (`/scenario/{id}`, `/attempt`) is now confirmed dead,
  unreachable frontend code — see the "Old decision-gate quiz path" note
  below.

Full backend suite: 439 passed, zero regressions, as of `d942266`
(also fixed a pre-existing flaky test in `test_scenarios_recent.py`
exposed by this item's new AsyncSessionLocal-based tests — see that
commit).

### Item 5 — Frontend

The automated dispatch agent that was supposed to build this ran 48 turns
against a genuinely fresh, correctly-triggered dispatch and produced no
branch/commit/PR at all — silently incomplete, not crashed, with no error
in the run logs. Not retried blind; built directly instead. (Separately,
the same dispatch agent produced nothing at all on a prior trigger too —
0 for 2. This is the incident `claude-dispatch.yml`'s removal, above, is
about.)

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
  debrief page needed. A persistent objective line, a map legend (colors
  sourced from the same `nodeStateColor` map the network map itself
  renders from), and a sparing idle nudge were added later as onboarding
  layer 1. The full guided first-run shipped in commit `9d58c58`
  (2026-07-27): a one-time in-fiction `ConsolePreBrief.tsx` handover
  screen before the map appears, plus three in-run beats keyed to the
  player's own first scan/query/block. Tracked server-side per account
  (`User.has_seen_console_intro`, `PATCH /auth/me`) so it fires exactly
  once ever, with a replay control in Settings (`UserProfilePage.tsx`)
  for testing. Not a Phase 5 item — already live.
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

### Close-out — compression, breach head-start, evidence display, is_synthetic, acceptance

Found and fixed while re-verifying this phase's acceptance criteria
against the game as it actually played, before closing it out:

- **`compression_ratio` scaling** — Colonial Pipeline's authored gates
  (+4m to +49m) were used as literal seconds against the 8/10-minute
  action-console caps, so ~10 of 12 gates fell past every mode's cap and
  could never fire in a playable session. `action_engine.py` now scales
  every trigger_timestamp by the scenario's `compression_ratio`
  (floor, deterministic, never preempts the final stage) before it
  becomes trigger_seconds.
- **`BREACH_HEAD_START_SECONDS`** — the compiled world previously started
  fully clean regardless of narrative premise; a responder walking into
  an "already in progress" breach saw a pristine network until they burned
  most of their budget getting there. The compiler now pre-folds a fixed
  amount of the (compressed) timeline into the starting world, so the
  first scan shows several hosts already compromised.
- **Evidence display fix** — querying/blocking against a compromised host
  previously spent the verb's cost with no visible result; the drawer only
  opened on a second, separate tap. `ActionConsole.tsx` now reacts to
  whatever the server just confirmed (`useRunSocket`'s `lastDelta`) and
  opens the right host's drawer or shows a result toast immediately.
- **`Scenario.is_synthetic`** (migration `0031`) — the daily-challenge
  picker could select test/fixture scenarios, because several tests
  commit real `status="approved"` rows to the shared dev DB. A leaked,
  un-flagged scenario from exactly this pattern was live-serving as an
  actual Daily Breach challenge in this environment before the fix. Now a
  real structural flag, not a title match; 323 pre-existing leaked rows
  remediated.
- **Old decision-gate quiz path (Daily Breach) — confirmed dead, not just
  unused.** No frontend component calls `GET /daily/scenario/{id}` or
  `POST /daily/attempt` anywhere — grepped the whole frontend tree, zero
  hits. `ResultsPanel` only displays a previously-recorded legacy
  `DailyAttempt` result; it has no gate-answering UI. The backend routes
  and `DailyAttempt` table stay (real historical rows still need to
  read/display correctly), but the PLAY path is unreachable dead code by
  design, not an oversight — documented here rather than deleted, since
  removing the routes/tests is a separate, lower-priority cleanup with no
  urgency now that nothing can reach them.
- `PHASE2_ACCEPTANCE.md` — all 9 spec section 4 criteria re-verified
  against the code above, 9/9 PASS. Criterion 3 rewritten (see that doc
  for the full reasoning: the original wording assumed a real-time clock,
  incoherent against this engine's turn-based spend-clock design). Core
  loop (scan → query → block → win, within the cap) confirmed end-to-end
  against a real compiled run.

Full backend suite: 467 passed, 0 failed, as of this close-out.

Merged to `main`: PR #21 (`08d0674`). Two small follow-up PRs landed the
same day: #22 (fixed a `claude-review.yml` bug where a re-review after a
fix could silently reuse a stale verdict from an older commit — found live
on PR #21 itself) and #23 (documented REVIEW_CRITERIA.md criterion (p): a
PR touching `.github/workflows/` structurally can't get a real automated
verdict — the reviewer's own GitHub App token hits a permission wall on
such diffs; admin-merge those directly on CI + hand review rather than
re-diagnosing this each time).

---

## Phase 2.5 — CMMC evidence layer (complete — shipped and production-verified 2026-08-07)

This section previously said "not yet scoped" — stale. The phase was
spec'd (`docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md`), built, and shipped
end to end. All 8 build-order items landed: multi-tenancy models,
consultant/client onboarding + invitations, `EvidenceSession` designation
from completed runs, notification matrix CRUD, after-action workflow
(lessons/remediation/IRP linkage/dual sign-off), evidence pack PDF
generation (HTML + Playwright/Chromium, not reportlab), Ed25519
signing/tamper-evidence, and consultant branding (logo + tagline).

A full real end-to-end walkthrough against production (real HTTP/WS, not
internal calls) covering the entire consultant flow — org bootstrap,
invites, two real scored gameplay runs, designation, notification
matrix, lessons/remediation/IRP linkage, dual sign-off, issuance,
download, public verification, byte-identical re-download — found and
fixed 4 real bugs, all shipped: `exercise_date` 500ing on any
timezone-aware ISO datetime, `POST /action-runs` returning a WS-only id
that silently differed from the persisted `ActionRun.id`,
`POST /admin/cmmc/consulting-orgs` not echoing `admin_email`, and the
evidence-pack download route 500ing on any non-latin-1 character in a
session title.

**No frontend UI exists for this layer, by design** — spec §9: "No
compliance language on the play surface." It's API + server-rendered PDF
only.

**Known, logged, unfixed gap** (see `docs/BACKLOG.md`): `contained_at_cost`
is mathematically unreachable on Colonial Pipeline and SolarWinds
specifically (decoy pools too small). Flagged for Phase 3 tuning.

Production signing key is live (`key_id=prod-20260807`); the private key
was generated inside the production container and handed to Femi once
for offline backup, never stored in this repo or in agent memory.

Local dev and production have **different** `Scenario` row ids for the
same conceptual scenario — not shared seed data. Don't assume a
`scenario_id` discovered in one environment works in the other.

---

## Phase 3 — in progress

The written spec's Phase 3 (`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` §5)
is "Juice pass + share cards." The two items below shipped under the
"Phase 3" label before that spec section documented them — added
retroactively to §5 as 3(a)/3(b) rather than left untraceable. Neither
touches `mastery_service.py`, `/mastery/me`, or Org Tabletop mode.

- **3(a) — Targeted escalation & notification proportionality**
  (migration `0038_scenario_notification_matrix`) — `scenarios.
  notification_matrix`: per-scenario authored ground truth for which
  parties a warranted notification decision covers, so `escalate` can
  finally be scored on proportionality (over-notifying a party the
  incident doesn't warrant now has a cost), mirroring how Proportionate
  Response already scores over-aggressive containment. Grounded in the
  CMMC evidence-pack bar (Carter Schoenberg, Lead CMMC Certified
  Assessor) logged as a Phase 3 follow-up in
  `docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md` §10. SolarWinds is the
  only scenario with a real authored matrix so far; the other 4 flagship
  scenarios are logged in `docs/BACKLOG.md`.

- **3(b) — Technique Dossier** (PR #31, PR #32) — cross-run tracking of
  which real-world MITRE techniques a player has encountered via the
  Action Console, for post-run debrief and player retention/skill-
  building (the same instinct behind `mastery_service`'s decision-gate
  accuracy tracking, extended to cover Action Console stage triggers,
  which `mastery_service` never did). Write side: `TechniqueEncounter`
  rollup rows (migration `0039_technique_encounters`), authenticated
  runs only. Read side: `GET /dossier/me`. Surfaced in the run-end
  debrief (`RunDebrief`, every run regardless of auth) and on a new
  standalone `/dossier` page — all 30 techniques grouped by tactic, a
  fill counter, full content for encountered techniques, locked
  placeholders for the rest.
