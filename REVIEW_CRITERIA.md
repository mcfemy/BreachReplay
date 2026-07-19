# Review Criteria — BreachReplay Game Overhaul

Standing rules for every review of a Phase 2+ PR, human or automated
(`.github/workflows/claude-review.yml`). These come out of this project's
actual QA history — several of the items below are things that were caught
in review and would otherwise have shipped broken.

## How to review

1. Read `docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` (the binding spec) and
   `STATE.md` (what item this PR is supposed to be, and what's
   already landed) before reading the diff. **A PR is reviewed against
   spec conformance, not just code quality.** A change that is
   well-written but implements the wrong thing, skips a required behavior,
   or drifts from the current item's stated scope is not approvable no
   matter how clean the code is.
2. Read the diff.
3. Trust CI's independently-run test result for this exact commit — do not
   re-run the suite yourself (see rule (i) below).
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
`STATE.md` before assuming either way.

## Non-blocking but required

**(h) No weakened assertions without justification.** An existing test's
assertion may not be loosened, removed, or made less specific unless the
diff includes written justification for why the old assertion was wrong —
"this test was in the way" is not justification. If you can't find the
justification in the PR description or a code comment, flag it as
blocking, not just a nit.

**(a, general) Conformance over style.** Prefer findings that say "this
doesn't match spec section 4's X" or "this isn't what `STATE.md`
describes for Item N" over generic code-quality nitpicks. Style/structure
feedback is welcome but must not be the bulk of the review — the spec is
the standard being enforced here.

## Process rule for the reviewer

**(i) Trust independent machine evidence; never trust the PR's own
claims.** This rule never actually required the reviewer to personally
re-run pytest — it required never accepting a PR description's or commit
message's claim of "tests pass" as evidence. `ci.yml` already runs the
full backend suite independently, in its own job, on the exact same
commit — that IS independent machine evidence, the same category as if
the reviewer had run it directly, and is trusted as such.
`claude-review.yml` waits for that check's conclusion via `gh` before
invoking Claude at all: a red CI check blocks the PR
immediately, with zero Claude turns spent analyzing a build already known
to be broken, and Claude is told CI's result as an established fact
rather than asked to re-verify it. This changed because the reviewer's
own duplicate `pytest -q` run was pure waste — CI had already produced the
identical answer, independently, for free, before Claude ever started.
What did NOT change: a PR description or commit message asserting "tests
pass," "verified locally," or similar is still never evidence on its own.
Only CI's own machine-reported conclusion on that exact SHA counts. A PR
whose description claims a green suite but whose CI check is red (or
never completed) is `CHANGES REQUESTED`/blocked, not `APPROVED` pending
clarification.

**(j) Distinguish "reviewer said no," "reviewer never finished," and "the
reviewer never got to start."** A real `VERDICT: CHANGES REQUESTED`, a
review run that crashed or hit its turn/time cap without posting a
verdict, and a run that never even started because the Claude API itself
was unreachable are THREE different signals, not one — a human (or the
next automated step) reading a red check must be able to tell all three
apart. The first two came out of PR #5's review run failing outright (no
verdict posted, ~5 minutes, red) with nothing distinguishing it from a
real CHANGES REQUESTED in the check history; `claude-review.yml`'s "Gate
the check on the posted verdict" step enforces the distinction
structurally, posting a visible `REVIEW ERRORED — no verdict, see run
logs` marker only when the review step itself failed or produced no
verdict line, never on a real verdict. The third came out of PR #12 and
PR #14 both failing with the identical signature — `is_error: true`,
under 500ms, exactly 1 turn, $0 cost — hours apart, on structurally
unrelated diffs, strongly indicating the Claude API itself was
unreachable (billing, auth, or quota) rather than either PR having a real
problem. A cheap 1-turn preflight call now runs before the real review
specifically to catch this signature early and post a distinctly-worded
`REVIEW UNAVAILABLE — ... not a problem with this PR` marker instead of
letting a dry balance masquerade as `REVIEW ERRORED` (which reads as "the
review crashed on this PR's content," a materially different and
misleading signal). All three outcomes still fail the check — branch
protection blocks the merge in every case — but the posted comment must
always make clear which of the three actually happened.

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

**(m) Turn budget scales to the diff, not a flat maximum.** `--max-turns`
is computed per-PR from the diff's total changed lines (15 by default, 50
only past ~400 changed lines), not hardcoded to 50 for every review
regardless of size. Two runaway reviews on PR #5 burned real money running
up against a flat 50-turn cap and produced nothing — a small PR has no
business being given the same budget as a 400+ line one. If the review
genuinely needs more turns than its tier allows and hits the cap, that's
still a `REVIEW ERRORED` outcome per (j) — the fix is to reconsider the
threshold or split the PR, not to raise the ceiling back to a flat maximum
"just in case."

**(n) The reviewer only runs on paths where its blocking criteria can
actually be violated.** Every blocking criterion above lives in a small,
specific set of files: leak safety (b) and playability (e) live in the
verb/WS layer; determinism (c) lives in `action_engine.compile_scenario`
and what it calls; org tabletop isolation (d) lives in
`simulation_ws_handler`/`ConnectionManager`; server authority (f) lives in
clock/score computation; migrations (g) is self-evidently
`backend/migrations/`. None of these can be violated by a docs change, a
workflow-file edit, a styling tweak, or a small route fix that doesn't
touch the paths above — CI's independently-run test suite (i) is a
complete, sufficient check for that class of change on its own.

Concretely, `claude-review.yml`'s `Compute diff stats` step skips the
Claude review entirely — a one-line `auto-skipped — CI is the gate`
comment and a passing check, no Claude invocation at all — unless the
diff touches at least one of:

- `backend/app/services/` (the compiler, verb engine, mastery/XP/pipeline
  services — where determinism and most of the domain logic live)
- `backend/app/websocket/` (leak safety, org tabletop isolation, server
  authority all live in the WS handlers)
- `backend/migrations/` (criterion (g) is entirely about this directory)
- `frontend/src/lib/*Socket*` and `frontend/src/store/` (the frontend
  halves of leak safety and server authority — a WS hook merging a
  server delta incorrectly, or a state store trusting a client-computed
  value, are the frontend-side ways (b)/(f) get violated)

This computation happens purely from `git diff --name-only`, before
anything costs money. It supersedes and subsumes the narrower docs-only
skip this criterion originally described — a docs-only PR is just one
instance of "touches none of the reviewed paths," not a special case
needing its own rule. PR #12 (docs-only, cost $0.42, produced no verdict —
the API-unavailable failure (j) now catches that class separately) was
the original motivating case; the broader rule additionally covers
config, workflow-file, styling, and small route-fix PRs that were
previously paying for a review that could never find anything a passing
CI run hadn't already proven. A PR that mixes any reviewed-path change
with unrelated files still gets the full review — this only skips when
**none** of the changed files touch a reviewed path.

**(o) The review model is pinned explicitly, not inherited.**
`claude-review.yml` passes `--model claude-opus-4-8` to both the
preflight and real review steps in `claude_args`. Before this, no model
was specified at all — `claude-code-action`'s own documentation never
states what model it defaults to, and the actual behavior had to be
confirmed directly from 5 real run logs on this repo (PR #12/#13/#14),
all of which independently reported `"model": "claude-opus-4-8[1m]"` in
their init message. That is: this review has been running on Opus the
entire time, silently, as an inherited default rather than a decision —
exactly the kind of unpinned dependency that can change cost or quality
out from under this workflow the moment the action's own default changes,
with no diff in this repo to explain why.

**(p) The reviewer cannot review a PR that touches `.github/workflows/`
— known limitation, do not re-diagnose from scratch.** A PR whose diff
includes any workflow-file change gets a real, expensive review attempt
(confirmed on PR #21 after `phase-2-action-console` picked up a
`claude-review.yml` fix: `num_turns: 30`, `total_cost_usd: 3.25`,
`is_error: false` — genuine multi-turn work, not a no-op or crash) that
nonetheless posts NO comment at all. The tell is
`permission_denials_count: 1` in the same result: the Claude GitHub App's
installation token structurally cannot act on a PR that modifies workflow
files (the same class of restriction referenced on PR #6/#7), so the run
completes "successfully" from the SDK's own point of view while never
reaching `gh pr comment`. Reproduced identically three times in a row on
PR #21 (~$3 each) before recognizing the pattern — do not spend further
retries rediscovering this. When a PR's diff includes `.github/workflows/`
changes: don't wait on the `review` check for it, and don't blind-retry
past two identical `permission_denials_count: 1` results looking for a
different outcome. Confirm CI (`test`) is green, read the workflow diff
by hand, and admin-merge directly (branch protection's `enforce_admins:
false` already permits this for repo owners) — the same evidence standard
this file already asks a human reviewer to apply, just without an
automated verdict this specific diff shape can never produce. A genuine
future fix would mean granting the App's token `workflows: write` (a
real permission/security decision, not a workflow-file tweak) or routing
workflow-file PRs through a separate reviewer identity — either is a
deliberate call for whoever owns the repo's GitHub App installation, not
something to improvise mid-PR.

Opus was kept deliberately rather than switched to a cheaper model,
specifically **because** of (n): the review is now rare by design, so
every review that actually runs already touches a path where leak
safety, determinism, org-tabletop isolation, or playability can
genuinely break. That's where the strongest available reasoning belongs,
not where it's cheapest to run — the volume that used to justify
economizing on model choice (a review on every PR, most of which could
never fail a blocking criterion) no longer exists after (n). Opus has
also already demonstrated the kind of cross-file lifecycle finding this
gate exists to catch: the block_ip/resync asymmetry on PR #8 (a live
delta silently under-reporting evidence a resync would show), found by
the automated reviewer and missed on an independent human pass. If the
model is ever revisited, that should be its own explicit decision with
its own stated reasoning — never a silent side effect of leaving
`--model` unset again.
