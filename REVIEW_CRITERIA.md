# Review Criteria — BreachReplay Game Overhaul

Standing rules for every review of a Phase 2+ PR, human or automated
(`.github/workflows/claude-review.yml`). These come out of this project's
actual QA history — several of the items below are things that were caught
in review and would otherwise have shipped broken.

## How to review

1. Read `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` (the binding spec) and
   `PHASE2_STATE.md` (what item this PR is supposed to be, and what's
   already landed) before reading the diff. **A PR is reviewed against
   spec conformance, not just code quality.** A change that is
   well-written but implements the wrong thing, skips a required behavior,
   or drifts from the current item's stated scope is not approvable no
   matter how clean the code is.
2. Read the diff.
3. Run the full backend test suite yourself (see rule (i) below).
4. Check every BLOCKING criterion below explicitly, pass/fail, not just a
   prose summary.

## Blocking criteria

Any one of these failing is grounds for `VERDICT: CHANGES REQUESTED`,
regardless of how good the rest of the PR is.

**(b) Leak safety.** No client-facing payload — a WebSocket event, a REST
response, or any `delta` — may ever contain: undiscovered `hidden_iocs` /
`IOCPlacement` entries, `matches_on` values, unfired `Stage` data,
`mitre_technique`, or any other `CompiledRun`/`RunState` internal that
hasn't been explicitly earned through a verb the player actually issued.
Check every new WS message builder and every new REST response shape by
hand — don't trust that "it looked fine when I skimmed it." A finding here
should point at the exact field and the exact code path that puts it on
the wire.

**(c) Determinism.** `action_engine.compile_scenario(scenario, seed)` must
remain byte-identical for the same `(scenario, seed)` pair. Phase 4's ghost
replay depends on this being true forever, not just today — a change that
introduces `datetime.utcnow()`, unseeded `random`, dict-iteration-order
dependence, or any other non-determinism into the compiler or anything it
calls is blocking even if every existing test still happens to pass.

**(d) Org tabletop isolation.** No PR may modify `simulation_ws_handler`'s
message-type branches or shared `ConnectionManager` presence/vote/pause
state (`manager.presence`, `manager.votes`, `manager.pause_events`, etc.).
Action-console/action-run code must stay in its own, separate code paths
(`action_run_ws_handler`, `action_run_store`, the `build_*` functions added
for action-mode events) — the same isolation Arena mode already
established for itself. `tests/test_org_tabletop_regression.py` must pass
**untouched** — a PR that "fixes" this test by changing its assertions
instead of leaving org tabletop alone is a blocking finding, not a pass.

**(e) Playability.** Any answer a verb requires must be reachable through
evidence the player can actually reveal in play — never only known
server-side. Concretely: an IP `block_ip` expects must appear in some
`raw_log` a `query_logs`/`image_disk` call can reveal; a hostname `isolate`
targets must be identifiable from revealed state, not just from
`matches_on`. A test that asserts correctness by reading `matches_on` or
another server-only field directly (instead of extracting the answer from
what was actually revealed to the player) does not satisfy this criterion
— see `test_block_ip_answer_is_discoverable_through_legitimate_play` for
the pattern this must match.

**(f) Server authority.** Clocks and run state never trust a
client-supplied value. `elapsed_seconds`/the attacker clock are computed
entirely server-side from fixed verb costs and real server timestamps; if
a new message type or field lets the client assert a time, score, or state
value that the server then uses without independently deriving it, that's
blocking.

**(g) Migrations.** Every migration must chain off the current head
(check `down_revision` against the actual latest file in
`backend/migrations/versions/`), have a complete, symmetric `downgrade()`
(not a stub), and pass a round-trip test (upgrade, verify schema/data,
downgrade, verify clean removal, re-upgrade). Prefer amending an
unmerged/undeployed migration over stacking a new one on top of it, if
that migration truly hasn't shipped yet — check with the PR author or
`PHASE2_STATE.md` before assuming either way.

## Non-blocking but required

**(h) No weakened assertions without justification.** An existing test's
assertion may not be loosened, removed, or made less specific unless the
diff includes written justification for why the old assertion was wrong —
"this test was in the way" is not justification. If you can't find the
justification in the PR description or a code comment, flag it as
blocking, not just a nit.

**(a, general) Conformance over style.** Prefer findings that say "this
doesn't match spec section 4's X" or "this isn't what `PHASE2_STATE.md`
describes for Item N" over generic code-quality nitpicks. Style/structure
feedback is welcome but must not be the bulk of the review — the spec is
the standard being enforced here.

## Process rule for the reviewer

**(i) Run the tests yourself.** The reviewer (human or Claude) must
actually run the full backend pytest suite in its own environment and
treat any failure as blocking. Never accept a PR description's or commit
message's claim of "all tests pass" as evidence — verify it directly:

```
cd backend && pytest -q
```

A PR whose description claims a green suite but which the reviewer cannot
independently reproduce as green is `CHANGES REQUESTED`, not `APPROVED`
pending clarification.
