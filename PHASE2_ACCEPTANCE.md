# Phase 2 Acceptance — Action Console Core Loop

Walks every acceptance criterion in `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md`
section 4 ("Phase 2 — Action console core loop") against real evidence: a
test that runs, code that was read, or a browser that was actually driven.
No criterion below is marked PASS on the strength of "the code looks like it
should do this" alone.

**This replaces the previous acceptance doc wholesale, not incrementally.**
A `PHASE2_ACCEPTANCE.md` exists on a different branch
(`phase2-acceptance-verification`, commit `439d925`) and reported 8/9 PASS
with criterion 3 an open FAIL. That pass predates all of the following,
done on `phase-2-action-console` since:

- **`compression_ratio` scaling** (`action_engine.py`'s `_compress_seconds`)
  — authored stage timestamps (Colonial Pipeline's real gates span +4m to
  +49m) are now scaled by the scenario's `compression_ratio` before
  becoming trigger_seconds. Without this, ~10 of Colonial Pipeline's 12
  gates fell past every mode's time cap and could never fire in a playable
  session — confirmed by direct compilation before the fix.
- **`BREACH_HEAD_START_SECONDS` seeded opening** — the compiled world now
  arrives with several hosts already compromised, instead of a pristine
  map that only ever shows activity after the player burns most of the
  budget getting there.
- **The query→block evidence loop actually displaying** — `ActionConsole.tsx`
  now opens a host's drawer and shows a result toast the instant the server
  confirms a verb's result, instead of requiring a second, unprompted tap to
  see what a paid-for action revealed.
- **`Scenario.is_synthetic`** — the daily-challenge picker excludes
  test/fixture scenarios structurally; a real, live Daily Breach challenge
  in this environment had been running on a leaked test scenario before
  this fix (see `docs/BACKLOG.md`).

Most of the old doc's evidence is about a version of this loop that no
longer exists. This doc re-verifies all 9 criteria from scratch against the
game as it plays today, and is explicit everywhere the verdict or its
reasoning changed.

**Result: 9 of 9 criteria PASS.** Criterion 3 is rewritten (the original
wording assumed a real-time clock and was incoherent against this game's
actual turn-based spend-clock design — see below) and now passes under its
corrected definition, verified end to end. The core loop itself (scan →
query → block → win, within the cap) is separately confirmed against a real
compiled run, not just unit-level pieces.

---

## Criterion 3 — rewritten

**Original wording (spec checklist, verbatim):** *"A player who does
nothing loses in ≤ 8 minutes (Daily) with a coherent narrative of what
happened."*

This assumes a clock that advances on its own — the spec's prose above the
checklist says so explicitly ("the breach advances through its real stages
... whether or not the player acts"), and the previous acceptance pass
(commit `439d925`) failed this criterion for exactly that reason: it traced
`action_run_ws_handler` and found no background tick, and correctly
reported that a do-nothing player's clock never leaves 0.

That trace was accurate. It is not a bug. `action_run_store.py`'s own module
docstring states the design directly:

> `RunState.elapsed_seconds` (verb_engine) — the GAME clock. Advances only
> by a verb's fixed cost ... `LiveRun.real_started_at` (this module) — a
> REAL wall-clock server timestamp ... Used ONLY to detect abandonment.

This is a turn-based spend-clock by design, not a real-time one with a
missing tick. "A player who does nothing" has no coherent failure mode
against a clock that only moves when spent — there is no natural path by
which such a player ever loses at all (only the unrelated abandonment
sweep, `action_run_store.sweep_expired`, eventually ends the connection,
and only via real wall-clock time, not the game's own narrative clock).
The original criterion was asking this engine to do something its actual
design makes incoherent, not something it forgot to do.

**Rewritten:**

> A player who spends the time budget without containing the breach loses,
> with a coherent narrative outcome — the final stage fires on hosts they
> failed to isolate.

**Verified** — `backend/tests/test_verb_engine.py:576`,
`test_spending_the_full_cap_without_containment_loses_with_a_coherent_narrative`.
Compiles a real Colonial-Pipeline-shaped scenario with `compression_ratio`
applied (`_COMPRESSED_SCENARIO`, seed 1), spends the entire 480s daily cap
on `scan_network` calls only — never isolating anything — and asserts all
three, together, not just a bare outcome string:

1. `is_run_over(run, cap_seconds=480)` is `True` (the cap actually ended it).
2. `attacker_clock_seconds(run) >= final.trigger_seconds` — the final stage
   genuinely fired; the loss isn't just a timeout with nothing behind it.
3. The final stage's real target host(s) are left `compromise_level !=
   "none"` and `isolated is False` in the resulting world — the concrete,
   inspectable "what happened": the attacker reached that host because it
   was never contained.

Confirmed independently outside pytest too, against the exact same fixture:

```
elapsed_seconds: 495 (cap= 480 )
is_run_over (cap): True
attacker_clock_seconds: 585 final.trigger_seconds: 367
outcome: loss
final target host(s) state: [('host-1', 'foothold', False)]
```

**PASS**, under the corrected definition. This is a genuine reversal from
the prior doc's FAIL — not because the gap it found was wrong (it wasn't),
but because the criterion it was checking against didn't describe a
coherent property of this engine's actual design.

---

## Core loop, end to end (explicit re-verification, per today's request)

Beyond the 9 checklist items, re-verified the whole player-facing loop
against one real compiled run — not individual mechanisms in isolation.

**`backend/tests/test_verb_engine.py:487`,
`test_core_loop_scan_query_block_and_win_are_all_reachable_within_the_cap`**
— compiles `_COMPRESSED_SCENARIO` at seed 1 (confirmed by direct inspection
before writing the test: two hosts pre-fired to `foothold` at t=0, one of
them bound to an IP-matched hidden IOC, final stage at 367s):

1. **`scan_network` reveals a seeded breach already in progress** — ≥1 host
   comes back non-`"none"` on the very first scan, not a clean map.
2. **`query_logs` on a compromised host returns its IOC, including a real
   C2 IP** — `185.220.101.34` appears in the revealed `raw_log` text.
3. **`block_ip` on that exact address contains the matched host** —
   `delta["correct"] is True` and the host is `isolated` afterward.
4. **The win condition is reachable within the cap** — isolating the final
   stage's real target before it fires, then letting the clock pass it,
   produces `determine_outcome(run) == "win"` at `elapsed_seconds == 290`
   (well inside the 480s daily cap, tighter than the 600s scenario cap).

Independently confirmed outside pytest against the same fixture:

```
1. scan_network -> red hosts at t=0: [('host-8', 'foothold'), ('host-9', 'foothold')]
2. query_logs( host-9 ) -> revealed_iocs: [{'rule_id': 'AUTH-009', 'raw_log': 'auth=success src_ip=185.220.101.34', ...}]
3. block_ip -> correct: True host_id: host-9
final stage trigger_seconds: 367 targets: ('host-1',)
elapsed_seconds at win check: 290  (cap=480 daily / 600 scenario)
4. outcome: win
```

Also driven through an actual browser earlier this session (not part of
this pytest pass, but the same real backend/DB, same code) against the real
Colonial Pipeline scenario: `query_logs` on a compromised host opened its
drawer automatically and showed the real evidence line; `block_ip` on the
extracted IP showed a "Correct — host isolated" toast and turned the host
green on the map. Screenshots from that pass exist in this session's
transcript; not re-attached here since the pytest test above is the
reproducible, CI-checked version of the same claim.

**Core loop: PASS.**

---

## The 9 criteria

### 1. Same scenario + seed always produces identical world state and stage timeline

**PASS — same verdict, meaningfully more to verify than before.**

`backend/tests/test_action_engine.py:48`,
`test_same_scenario_and_seed_produce_a_byte_identical_compiled_run` — still
passes, still the base determinism guarantee.

**What's different:** `compile_scenario` now does two additional pieces of
work before returning a `CompiledRun` — scaling every trigger_timestamp by
`compression_ratio` and pre-folding `BREACH_HEAD_START_SECONDS` worth of
stages into `world`. Both had to be re-proven deterministic on their own,
not assumed to inherit the base guarantee for free:

- `test_action_engine.py:223`,
  `test_compression_ratio_scales_trigger_seconds_and_stays_deterministic` —
  compiles the same (scenario, seed) twice with `compression_ratio=8.0` and
  asserts byte-identical stages/alert_lines/ioc_placements; separately pins
  the floor-not-round policy (`test_action_engine.py:214` /
  `test_compress_seconds_floors_rather_than_rounds`) and the invalid-ratio
  fallback (`test_compress_seconds_falls_back_to_no_scaling_for_invalid_ratio`).
- `test_action_engine.py:270`,
  `test_breach_head_start_pre_fires_several_hosts_and_stays_deterministic` —
  same determinism check for the pre-fired `world`, plus
  `test_action_engine.py:293`,
  `test_breach_head_start_never_reaches_the_final_stage_of_a_short_scenario`
  (the head start can never accidentally pre-fire the loss condition
  itself) and `test_action_engine.py:313`,
  `test_new_run_world_matches_world_state_at_zero_and_advances_without_double_firing`
  (the live run's starting `world` matches `world_state_at(compiled, 0)`
  exactly, and the first live verb never re-applies a stage the compiler
  already folded in — this is what makes `verb_engine.new_run`'s negative
  initial `attacker_clock_offset` trick safe).

All pass. **PASS, with materially expanded coverage over the prior doc.**

### 2. Client never receives undiscovered IOCs or future stages

**PASS — same verdict, one new interaction re-verified.**

Unchanged evidence, still passing: `test_verb_engine.py:291`,
`test_no_verb_response_ever_leaks_unrevealed_hidden_state`, plus the
`action_run_ws_handler` resync tests in `test_action_run_ws_handler.py`.

**What's different:** `BREACH_HEAD_START_SECONDS` means `run.world` now
has compromised hosts from the instant a run starts — before this existed,
"nothing has happened yet" and "nothing has been revealed yet" were the
same fact. Now they aren't, and the fog-of-war guarantee had to be
re-checked against a world that already has something to leak.

`test_verb_engine.py:530`, `test_no_leak_on_initial_resync_despite_a_pre_fired_world`
— compiles a scenario confirmed to have a pre-fired host, then asserts
`earned_state_snapshot(new_run(compiled))` — what a fresh WS connect
resyncs to, per `action_run_ws_handler` — is exactly `{"hosts": [],
"revealed_iocs": [], "edges": []}` regardless. Holds because
`RunState.revealed_host_ids` defaults to an empty `frozenset` independent
of `world`'s compromise levels; only `query_logs`/`scan_network`/
`image_disk` ever populate it. This exact interaction had no prior test
coverage — it couldn't have, since the world it's testing didn't exist
before today.

**PASS, with one new regression test this exact change required.**

### 3. See rewrite above.

**PASS** (rewritten definition).

### 4. A skilled run can win with time to spare; a sloppy run can still partially recover — 5 seeded runs differ by strategy, not luck

**PASS — but the evidence for this on THIS branch did not exist until today.**

The prior acceptance doc cited `test_five_seeded_runs_win_or_lose_by_strategy_not_luck`
as satisfying this — but that test was added on `phase2-acceptance-verification`,
a different branch, and was never present on `phase-2-action-console`. This
branch had only the single-seed mechanism tests
(`test_outcome_is_win_when_final_stage_target_is_isolated_before_it_fires`,
`test_outcome_is_partial_when_final_fires_but_most_of_the_rest_is_contained`)
— real coverage of the mechanism, but not what the checklist item literally
asks for (5 seeds, strategy vs. luck).

Added fresh: `test_verb_engine.py:550`,
`test_five_seeded_runs_win_or_lose_by_strategy_not_luck`. For seeds 1–5
against the compressed (realistically-timed) scenario: isolating the final
stage's real target before it fires wins every time; isolating an
unrelated, off-attack-path host instead never does. Outcome tracks the
choice, not the seed, across all 5.

**PASS — flagged explicitly because the prior doc's citation for this
criterion did not apply to this branch at all; it does now.**

### 5. `escalate` usable exactly once; clock freeze verified

**PASS — same verdict, verified against a new interaction the old doc
never had to consider.**

`test_verb_engine.py:135`, `test_escalate_is_rejected_on_second_use`, and
`test_verb_engine.py:152`,
`test_escalate_freezes_the_attacker_clock_by_a_permanent_60s_offset` — both
still pass unmodified.

**What's different:** `verb_engine.new_run` (`verb_engine.py:87`) now seeds
`attacker_clock_offset` at `-compiled.breach_head_start_seconds` instead of
always starting at exactly 0 — the mechanism `escalate` relies on
(`attacker_clock_seconds`, `verb_engine.py:109`) is the same field the head
start now also uses. The existing tests happen to run against a fixture
whose head start computes to 0 (its gates are too far apart to pre-fire
anything), so they don't by themselves prove escalate still composes
correctly on top of a *nonzero* head start. Checked directly:

```
breach_head_start_seconds: 90
attacker_clock_seconds at t=0 (should equal head start): 90
after escalate: attacker_clock_offset = -30 (head_start - 60 = 30)
attacker_clock_seconds right after escalate (elapsed still 0): 30
```

Escalate's fixed 60s subtracts from whatever the offset already was,
exactly as the arithmetic (`offset + ESCALATE_FREEZE_SECONDS`) says it
should — it partially cancels the head start's lead rather than behaving
differently near it. **PASS**, with this composition now explicitly
checked rather than incidentally true.

### 6. XP, achievements (`speed_demon`, `perfect_analyst`, streaks) all fire from action runs

**PASS — unaffected by today's changes, same evidence as before.**

`test_action_run_store.py:151`,
`test_finalize_unlocks_perfect_analyst_and_speed_demon_on_a_realistic_fast_win`;
streaks via `test_daily_action_mode.py:334`,
`test_daily_run_end_carries_over_streak_and_rank_fields` and
`test_daily_action_mode.py:394`,
`test_swept_daily_run_broadcasts_run_end_and_carries_over_streak`. All
confirmed still present and passing on this branch. Nothing about
compression, head-start, or the console UI touches scoring/XP wiring.

### 7. Old org tabletop sessions (decision-gate mode) unaffected

**PASS — unaffected, same evidence as before.**

`test_org_tabletop_regression.py:114`,
`test_org_tabletop_decision_gate_flow_is_unaffected_by_phase_2` — passes
unmodified. Structural isolation from `action_run_ws_handler` is unchanged
by today's work (no edits to `simulation_ws_handler` or
`ConnectionManager`'s presence/vote/pause state). The one edit this file
received today was adding `is_synthetic=True` to its test fixture — a test
data hygiene fix (see intro), not a behavior change; the test's own
assertions are untouched.

### 8. Full loop playable on a phone with one thumb

**PASS — re-verified fresh, now including onboarding UI that didn't exist
in the prior pass.**

Re-driven with Playwright at a 390px viewport against the live dev stack
this session, not assumed from the prior pass:

- `ActionConsole.tsx` at 390px: objective line (`ActionConsole.tsx:245`)
  wraps to two short lines rather than truncating — confirmed fixed after
  an initial version clipped it — legend badge (`ActionConsole.tsx:263`)
  sits in a `pointer-events-none` corner overlay that never blocks a tap,
  colors read live from `nodeStateColor.compromised`/`.contained`
  (`ActionConsole.tsx:267,274`) so they cannot drift from what the map
  itself renders. Idle nudge (`ActionConsole.tsx:158`, 25s threshold)
  confirmed to fire once at ~t=27s, self-dismiss by ~t=32s, and NOT re-fire
  at t=52s of continued inactivity in the same idle stretch. None of this
  existed in the prior acceptance pass.
- The query→block evidence loop itself, screenshotted at 390px: `query_logs`
  on a red host opens its drawer with real evidence automatically; `block_ip`
  on the extracted IP shows a result toast and the host goes green on the
  map. This is the fix for the core bug this session started from (querying
  a compromised host previously showed nothing at all) — now confirmed
  working at mobile width, not just desktop.
- AppShell's hamburger/drawer mobile collapse (PR #11, cited in the prior
  doc) — re-confirmed live on THIS branch, not assumed merged-and-therefore-fine:
  no horizontal overflow at 390px, hamburger opens a slide-in drawer with
  the full nav (Daily Breach, Red Team, Arena, etc.) legible over a dimmed
  backdrop.

**PASS**, on fresher and broader evidence than the prior pass had available.

### 9. pytest suite green in CI, including new engine tests

**PASS.**

Full `pytest -q` against a freshly-cleaned local dev database:
**463 passed, 0 failed, 0 skipped.** This is 4 more than the prior doc's
445 (test_five_seeded_runs_win_or_lose_by_strategy_not_luck,
test_core_loop_scan_query_block_and_win_are_all_reachable_within_the_cap,
test_no_leak_on_initial_resync_despite_a_pre_fired_world,
test_spending_the_full_cap_without_containment_loses_with_a_coherent_narrative
— all four added by this pass) plus everything else accumulated on this
branch since (compression/head-start unit tests, the `is_synthetic`
migration, etc.).

**Local-environment caveat, materially improved since the prior doc:** the
prior pass flagged `test_daily_action_mode.py` and `test_action_run_ws_handler.py`
writing real, non-rolled-back rows against the shared dev DB via
`AsyncSessionLocal` as a source of local-only flakiness, and left it as
"worth a proper fix ... not blocking." Since then this became a confirmed
**production-safety incident, not just test noise**: a leaked, un-flagged
test scenario from exactly this pattern was selected by the real
daily-challenge picker and served as an actual live Daily Breach challenge
in this environment. Fixed structurally — `Scenario.is_synthetic`
(migration `0031_scenario_is_synthetic`), the daily-challenge picker now
filters on it (`daily.py:233`), all 323 pre-existing leaked rows were
remediated (archived + flagged), and the three test fixtures responsible
(`test_daily_action_mode.py`, `test_action_run_ws_handler.py`,
`test_org_tabletop_regression.py`) now set `is_synthetic=True` at creation.
The literal-future-date collision behavior itself (rows from a failed run
colliding with the next run's insert) is unchanged and still local-only —
CI, which always starts from a fresh database, remains unaffected either
way.

---

## Summary

| # | Criterion | Verdict | Changed since prior doc? |
|---|---|---|---|
| 1 | Determinism | PASS | Same verdict; compression + head-start scaling now separately proven deterministic |
| 2 | No leak of undiscovered state | PASS | Same verdict; new regression test for the pre-fired-world case |
| 3 | Turn-based spend-clock loss, coherent narrative | **PASS** | **Rewritten definition** (was FAIL under the old, incoherent real-time wording) |
| 4 | Strategy beats luck across 5 seeds | PASS | Test didn't exist on this branch before this pass — added fresh |
| 5 | `escalate` once + clock freeze | PASS | Same verdict; composition with nonzero head start explicitly checked |
| 6 | XP/achievements/streaks fire | PASS | Unaffected, unchanged |
| 7 | Org tabletop regression | PASS | Unaffected, unchanged (fixture got `is_synthetic=True`, not a behavior change) |
| 8 | Phone, one thumb | PASS | Re-verified fresh; now covers onboarding UI + the query/block display fix |
| 9 | pytest suite green | PASS | 463 passed (was 445) — 4 new tests from this pass; production-safety gap from the old caveat now fixed |

Core loop (scan → query → block → win, within the cap): **confirmed
end-to-end** against a real compiled run, both in a reproducible pytest
test and independently in a live browser session.

**Phase 2 is ready to close.** No criterion is marked PASS without a
currently-passing test or a freshly-driven browser session behind it; every
place today's changes altered a criterion's evidence or verdict is called
out above rather than silently re-stamped PASS.
