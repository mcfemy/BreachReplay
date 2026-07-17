# Phase 2 Acceptance — Action Console Core Loop

Walks every acceptance criterion in `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md`
section 4 ("Phase 2 — Action console core loop") against real evidence: a
test that runs, code that was read, or a browser that was actually driven.
No criterion below is marked PASS on the strength of "the code looks like it
should do this" alone.

**Result: 8 of 9 criteria PASS. One (do-nothing-player timing) is a real,
confirmed gap — reported honestly below, not glossed over, with a follow-up
logged to `docs/BACKLOG.md`.**

---

## 1. Same scenario + seed always produces identical world state and stage timeline

**PASS.**

`backend/tests/test_action_engine.py:48`,
`test_same_scenario_and_seed_produce_a_byte_identical_compiled_run` —
compiles the same scenario dict twice with the same seed and asserts the two
`CompiledRun`s are equal (frozen dataclasses, structural equality). A second
test at line 90, `test_world_state_at_progresses_deterministically_with_elapsed_time`,
covers the derived timeline the same way. Both pass in the current suite.

## 2. Client never receives undiscovered IOCs or future stages

**PASS.**

Two independent layers of evidence, both currently passing:

- `backend/tests/test_verb_engine.py:291`,
  `test_no_verb_response_ever_leaks_unrevealed_hidden_state` — plays a
  realistic verb sequence and asserts, after every single call, that no
  forbidden structural key (`stages`, `trigger_seconds`, `mitre_technique`,
  `hidden_iocs`, `matches_on`, …) and no undiscovered IOC's text ever appears
  in the delta JSON.
- `backend/tests/test_action_run_ws_handler.py` — `_MULTI_HOST_HIDDEN_IOCS`
  fixture plus `test_fresh_connect_sends_a_run_resync_event_at_zero` (a
  fresh connect must resync to `hosts: []`, `revealed_iocs: []`, `edges: []`)
  and `test_resync_after_scan_and_query_returns_exactly_the_earned_subset`
  (a reconnect after partial play must resync to *exactly* what was earned,
  nothing more). This second layer exists because of a real bug found and
  fixed during Item 5 planning: `build_run_resync_event` originally sent
  only clocks, never earned world state — a reconnecting player lost every
  host/IOC they'd already discovered. Fixed in `verb_engine.earned_state_snapshot`
  + `manager.build_run_resync_event` (see `PHASE2_STATE.md`'s Item 5 entry).

## 3. A player who does nothing loses in ≤ 8 minutes (Daily) with a coherent narrative

**FAIL — confirmed real gap, not a false alarm.**

The spec's own loop description (section 4, "The loop (player's view)")
states: *"the breach advances through its real stages ... whether or not the
player acts."* The actual implementation does not do this.

Traced end to end in `backend/app/websocket/handlers.py`,
`action_run_ws_handler` (line 1527 on): the entire clock-advancing and
`is_over` check lives inside `while True: raw = await websocket.receive_text()`
(line 1560) — it only runs in reaction to a client `action.submit` message.
There is no background task ticking a connected-but-idle run's
`elapsed_seconds` independent of player input. `verb_engine.RunState.elapsed_seconds`
only ever advances inside `apply_verb` (spent per verb cost); `attacker_clock_seconds`
is derived from it. A player who never sends a single verb keeps the server
sitting in `receive_text()` forever, clock frozen at 0 — the "attacker" never
progresses at all, the opposite of "advances whether or not the player acts."

The only thing that eventually ends such a run is the unrelated abandonment
sweep (`action_run_store.sweep_expired`, wired via
`app.main._run_action_run_sweep_iteration`), which force-finalizes a run once
real wall-clock time exceeds `cap_seconds + SWEEP_GRACE_SECONDS`
(`backend/app/services/action_run_store.py:55,65`). For Daily,
`cap_seconds=480` (8 min) + `SWEEP_GRACE_SECONDS=60` = **540s (9 minutes)**,
not ≤ 8 minutes. And because `elapsed_seconds` never advanced, the resulting
`run.end` summary reflects an empty `action_log`, zero evidence found, and no
stage ever having fired internally — a technically-correct `outcome="loss"`
but not the *"coherent narrative of what happened"* the criterion promises;
there is no "what happened" to narrate.

This is a real design gap, not a rounding error: closing it means adding a
genuine real-time tick to the live run (independent of verb submission) so
the attacker clock — and therefore the narrative — progresses whether or not
the player acts, matching the spec's own stated design. That's a
meaningful architecture change (a background per-run ticker, clock-drift
handling, tick broadcasts to a possibly-idle socket), not something to bolt
onto an acceptance-verification pass. Logged as a new entry in
`docs/BACKLOG.md` for prioritization before Phase 3 gameplay-balance work.

## 4. A skilled run can win with time to spare; a sloppy run can still partially recover — 5 seeded runs differ by strategy, not luck

**PASS.**

`backend/tests/test_verb_engine.py`,
`test_five_seeded_runs_win_or_lose_by_strategy_not_luck` (added as part of
this acceptance pass) — for seeds 1 through 5, plays two strategies against
each seed's compiled world: isolating the final stage's actual target host
(wins every time) versus isolating an unrelated, off-attack-path host while
the real target fires unopposed (never wins). Outcome tracks the choice, not
the seed. Complements two pre-existing single-seed tests covering the same
mechanism directly: `test_outcome_is_win_when_final_stage_target_is_isolated_before_it_fires`
and `test_outcome_is_partial_when_final_fires_but_most_of_the_rest_is_contained`.

## 5. `escalate` usable exactly once; clock freeze verified

**PASS.**

`test_escalate_is_rejected_on_second_use` (second call returns
`error == "escalate already used this run"`, run state unchanged) and
`test_escalate_freezes_the_attacker_clock_by_a_permanent_60s_offset` (35s of
subsequent real elapsed time still reads `attacker_clock_seconds() == 0`,
i.e. `max(0, 35 - 60)`) — both in `backend/tests/test_verb_engine.py`, both
passing.

## 6. XP, achievements (`speed_demon`, `perfect_analyst`, streaks) all fire from action runs

**PASS.**

`backend/tests/test_action_run_store.py`,
`test_finalize_unlocks_perfect_analyst_and_speed_demon_on_a_realistic_fast_win`
— plays a realistic fast/clean win through the real `ActionRunStore.finalize`
path and asserts both achievements unlock and `xp_awarded > 0`. Notable
because `xp_service.check_scenario_achievements` had **zero callers**
anywhere in the backend before Phase 2 Item 3 (see `docs/BACKLOG.md`'s
"Decision-gate scenario completion never awards XP" entry for the
still-open gap on the *old* decision-gate path — genuinely pre-existing and
out of Phase 2's scope, not something this phase regressed). Streaks are
covered separately: `backend/tests/test_daily_action_mode.py`,
`test_daily_run_end_carries_over_streak_and_rank_fields` and
`test_swept_daily_run_broadcasts_run_end_and_carries_over_streak` both
assert `current_streak`/`longest_streak`/`total_dailies_played` carry over
correctly from a real `record_daily_action_run_result` call.

## 7. Old org tabletop sessions (decision-gate mode) unaffected

**PASS.**

`backend/tests/test_org_tabletop_regression.py`,
`test_org_tabletop_decision_gate_flow_is_unaffected_by_phase_2` — passes,
unmodified, in the current suite. Structurally enforced beyond this one
test: `action_run_ws_handler` and `simulation_ws_handler` share no message
branches, no `ConnectionManager` presence/vote/pause state, and no
`SimulationSession`/`SessionParticipant`/`SessionDecision` involvement
(see the isolation comment at `backend/app/websocket/handlers.py:1486`).
Every PR touching this loop since Item 3 has had this checked explicitly by
the automated reviewer (REVIEW_CRITERIA.md criterion (d)); PR #10 and #11's
reviews both confirmed "no change to `simulation_ws_handler` branches or
`ConnectionManager` presence/vote/pause state."

## 8. Full loop playable on a phone with one thumb

**PASS.**

Verified with a real browser, not claimed: Playwright at a 390×844 viewport
(iPhone-sized), logged in against the live dev stack, launched a real
scenario via `POST /action-runs`, and loaded `/run/:runId`.

- No horizontal overflow at 390px before or after interaction
  (`document.documentElement.scrollWidth <= clientWidth`, checked both at
  initial load and after tapping `scan_network`).
- The verb console renders as a clean 4×2 tap-target grid
  (`frontend/src/components/ActionConsole.tsx:244`, `grid-cols-4`,
  `min-h-[52px]` chips) — built mobile-first from the start in Item 5, no
  retrofit needed.
- After `scan_network`, the network map renders all 8 hosts with edges,
  fully legible, no overlap, no clipped labels.
- `AppShell.tsx` (shared chrome around every authenticated page, including
  this one) collapses its sidebar into a hamburger-triggered slide-in
  drawer below `md:`, merged in PR #11 — confirmed via its own Playwright
  pass at 390px (drawer closed/open/after-nav) plus 1280px (desktop
  unchanged), and via the automated reviewer's independent pass on that PR.

Screenshots from this pass:
`mobile_console_1_initial.png` (onboarding modal, console visible behind
it), `mobile_console_2_scanned.png` (post-scan network map + verb grid).

## 9. pytest suite green in CI, including new engine tests

**PASS**, with one local-environment caveat worth recording so it isn't
mistaken for a regression later.

A full `pytest -q` run against a freshly-cleaned local dev database:
**445 passed, 0 failed.** This includes the new
`test_five_seeded_runs_win_or_lose_by_strategy_not_luck` test added for
criterion 4 above.

Caveat: several tests in `test_daily_action_mode.py` write real, committed
rows via `AsyncSessionLocal` directly (documented in that file's own module
docstring — `finalize()` opens its own session, a different connection than
the `db` fixture's rolled-back one, so this is deliberate, not a bug). Those
rows use hardcoded literal future dates (`2030-02-0x`) specifically so they
don't collide with real production data, but repeated local test runs on the
same machine *do* collide with each other — both on the `daily_challenges
.challenge_date` unique constraint and, less obviously, on `user_streaks`
(a fixed test user's `current_streak` increments further on each rerun
within the same calendar day, since `_update_streak`'s idempotency guard
only resets at real midnight). This produced 2–4 spurious local failures
before each clean run during this acceptance pass; all resolved by deleting
the `>= 2030-01-01` `daily_challenges`/`action_runs` rows and the affected
`user_streaks` rows. This is a pre-existing local-only test-infra property
(not something this pass introduced or fixed) — CI, which always starts
from a fresh database, is unaffected. Worth a proper fix (e.g. a
session-scoped cleanup fixture for this file) before it causes confusion
again; not blocking Phase 2 acceptance.

---

## Summary

| # | Criterion | Verdict |
|---|---|---|
| 1 | Determinism | PASS |
| 2 | No leak of undiscovered state | PASS |
| 3 | Do-nothing player: ≤8min + coherent narrative | **FAIL — real gap, see above** |
| 4 | Strategy beats luck across 5 seeds | PASS |
| 5 | `escalate` once + clock freeze | PASS |
| 6 | XP/achievements/streaks fire | PASS |
| 7 | Org tabletop regression | PASS |
| 8 | Phone, one thumb | PASS |
| 9 | pytest suite green | PASS |

Criterion 3 is the one item that should not be considered closed. It is a
real behavioral gap against the spec's own stated design (the attacker clock
does not advance without player action, contradicting "whether or not the
player acts"), not a test-coverage gap — no amount of additional testing
closes it without an actual code change (a real-time per-run tick). Logged
to `docs/BACKLOG.md` for prioritization.
