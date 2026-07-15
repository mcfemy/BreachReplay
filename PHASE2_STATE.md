# Phase 2 State — Action Console Core Loop

Source of truth: `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` section 4 and
`docs/PHASE2_KICKOFF.md`. **Update this file in every item PR** — the
automated review workflow (`.github/workflows/claude-review.yml`) reads it
on `VERDICT: APPROVED` to post the next item's instructions.

Branch: `phase-2-action-console`, off `main` (Phase 1 merged at `ee4a57b`).
Every item lands on its own branch, PR'd into `phase-2-action-console`.

## Status: Items 0–3 complete and QA-approved. Item 4 next.

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

## Item 4 — Daily Breach action mode (next)

Switch daily challenge generation to action mode:

- **Deterministic daily seed** — same scenario + the same seed for every
  player on a given calendar day, not `secrets.randbelow` (that's for
  `POST /action-runs`' individual-scenario path only). Derive the seed
  reproducibly from the date + scenario id so replaying "today's seed"
  always gives the same `CompiledRun` — this is load-bearing for
  same-day-leaderboard comparability and for Phase 4 ghosts.
- **One run per user per day**, enforced server-side — a second creation
  attempt for a day already played must not silently create a second
  `ActionRun`; check the existing `daily_challenge`/`DailyAttempt` models
  for how this is already enforced on the decision-gate path and mirror
  that constraint for action-mode runs.
- **8-minute cap enforced server-side, mid-loop** — not only via
  `action_run_store`'s abandonment sweep. Needs a test that actually plays
  a run past the cap inside a single WS session (via repeated
  `action.submit` calls, like `test_run_over_triggers_finalize_and_a_run_end_event`)
  and confirms the server force-ends it — the sweep-based abandonment test
  alone does not cover this.
- **`run.end` broadcast carry-over** — check the current `daily_challenge`
  model / `backend/app/api/routes/daily.py` / `DailyBreachPage.tsx` for
  whatever fields the existing streak/leaderboard chrome expects before
  inventing new ones on the `run.end` payload.
- **Streaks and leaderboard read from `action_runs.total_score`** — that
  column exists specifically so this query can `ORDER BY` a real indexed
  integer instead of a JSONB path; don't reach into `score_breakdown` for
  ranking.
- **The old decision-gate daily quiz path stays intact but unreferenced.**
  Do not delete it, do not modify it — stop wiring *new* daily challenge
  generation through it. Mirrors REVIEW_CRITERIA.md's org-tabletop
  isolation rule (d): the two paths coexist, they don't share mutated
  state.

## Item 5 — Frontend (after Item 4)

- `ActionConsole.tsx` — 8 verb chips + cost labels, targets picked by
  tapping the network map (Phase 1's `NetworkMap.tsx`, reused), mobile-first
  (a desktop command input is secondary sugar, not the primary path).
- Rework `DailyBreachPage.tsx`'s gameplay section to action mode; keep the
  existing streak/score/leaderboard chrome unchanged.
- `SimulationRoomPage.tsx` — add "Compressed Run (10 min)" as the default
  mode for individual users; org sessions' full tabletop flow stays
  untouched (same isolation rule as the backend).
- Clock UI: redacted stage-progress bar in `bleed` (design tokens from
  Phase 1's `frontend/src/theme/tokens.ts`). Fog of war: unexamined hosts
  render dim/unknown until earned via `scan_network`/a reveal verb.

## After Item 5

Full Phase 2 acceptance-criteria verification against
`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` section 4's checklist —
determinism test, anti-leak test, a do-nothing player losing in ≤8 minutes
with a coherent narrative, five seeded runs differing meaningfully by
strategy, phone-with-one-thumb playability, pytest green in CI — before
declaring Phase 2 done.

## Phase 2.5 (queued after Phase 2)

CMMC evidence layer — see `docs/BACKLOG.md`.
