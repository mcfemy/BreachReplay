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

**(j) Distinguish "reviewer said no" from "reviewer never finished."** A
real `VERDICT: CHANGES REQUESTED` and a review run that crashed, hit its
turn/time cap, or otherwise died without posting any verdict are NOT the
same signal, and a loop that conflates them is not trustworthy — a human
(or the next automated step) reading a red check must be able to tell
"the reviewer looked at this and said no" from "the reviewer never
actually looked." This came out of PR #5's review run failing outright
(no verdict posted, ~5 minutes, red) with nothing distinguishing it from a
real CHANGES REQUESTED in the check history. `claude-review.yml`'s "Gate
the check on the posted verdict" step enforces this structurally: it fails
the check either way (so branch protection blocks the merge in both
cases), but only posts a visible `REVIEW ERRORED — no verdict, see run
logs` marker when the review step itself failed or produced no verdict
line — never when a real verdict (either one) was posted. Any future
review automation must preserve this distinction, not just "make the
check red on any problem."

**(k) Auto-fix trigger convention.** When a review posts `VERDICT: CHANGES
REQUESTED`, the SAME top-level comment must end with the literal line
`@claude address the numbered items above in this PR's branch` — this is
what actually starts the next fix round, since `claude.yml` only reacts to
an explicit `@claude` mention in a PR comment. Do not include this line on
`APPROVED`.

Know WHICH identity is posting before assuming a token fix is needed. A
comment posted via a workflow job's own default `GITHUB_TOKEN` does NOT
trigger other workflows — GitHub deliberately suppresses that to prevent
workflow-recursion loops — but `claude-code-action@v1` does NOT use the
default `GITHUB_TOKEN` unless a `github_token` input explicitly overrides
it: by default it authenticates as the Claude GitHub App's own
installation token, which posts as `claude[bot]`, a real actor already
exempt from the suppression. Confirmed directly against PR #4's review
comment (`author: "claude"`), not assumed. `claude-review.yml` briefly
carried a `github_token: secrets.CLAUDE_BOT_PAT` override built on the
wrong assumption that this step used the default token — that override
didn't just fail to help, it silently broke posting entirely (the review
ran its full turn budget and posted nothing, no error). Before adding any
token override to fix a "mention didn't fire" problem, check the actual
comment author on a run that DID post successfully — don't assume which
token was in play.

**(l) Item kickoff is human-initiated, not automated.** There used to be
a `claude-dispatch.yml` that auto-started the next Phase 2 item on PR
merge — removed. It went 0 for 2: on both Item 4's and Item 5's merges it
ran to completion, reported success, and pushed no branch, no commit, no
PR — silently, with no error anywhere in the run logs, structurally
indistinguishable from "nothing to do" without checking by hand. Items 4
and 5 both turned out to require a real design call *before* any code
could be written (Item 4: the daily-challenge seed/leaderboard model;
Item 5: whether solo-run routing lived in `SimulationRoomPage.tsx` or a
new page, and the `run.resync` earned-state gap found only by tracing the
actual WS contract) — exactly the kind of judgment a blind, unattended
agent has no way to make safely, and its silent-nothing record on both
suggests the *abstraction* was wrong, not just a bug in the workflow file
worth patching. The reviewer (`claude-review.yml`) and the `@claude`
auto-fix mention (`claude.yml`, criterion (k)) are unaffected by this —
both are mechanical, narrowly-scoped, and have now run correctly for
real. If a fully-automated next-item dispatcher is reintroduced later, it
must fail the job loudly whenever it completes without pushing a branch —
"ran successfully and did nothing" must never again be a silent,
indistinguishable-from-idle outcome.
