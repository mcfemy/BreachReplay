# Test database safety — spec

Status: **specced, not implemented.**

## Problem

Two production incidents in one evening (2026-07-24/25), same root cause:
tests write real, non-rolled-back rows via `app.db.session.AsyncSessionLocal`
directly — bypassing `conftest.py`'s rolled-back-transaction `db` fixture —
against whatever database `DATABASE_URL` actually resolves to at the time.

1. **The WS Handler scenario leak** (pre-existing, documented in
   `docs/BACKLOG.md`): a test-created `Scenario` row (`is_synthetic` now
   guards against this specifically) was picked up by the real Daily
   Challenge picker in this environment.
2. **Tonight**: running the full suite twice inside the deployed backend
   container (`docker exec breachreplay-backend-1 python -m pytest tests/`
   — the standard way to verify a change before a real deploy, used
   throughout tonight's host-namespace-unification work) left real rows in
   production — `daily_challenges` (colliding on a unique `challenge_date`
   on the second run), `action_runs`, `user_streaks`, and `users` with
   obviously-test-shaped ids (`daily-rank-a`, `action-run-owner-7`, etc.).
   Cleaned up by hand (verified read-only first, then deleted in FK order).

**Why this happens:** `conftest.py` does
`os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")` —
`setdefault` only applies when nothing already set the variable. Inside a
deployed container, `docker-compose`'s `env_file: .env.prod` injects the
real Postgres `DATABASE_URL` into the container's environment *before*
Python ever starts, so `conftest.py`'s default never fires.
`app.db.session.AsyncSessionLocal` (built from `Settings.DATABASE_URL`)
therefore resolves to the real production database, and every test helper
that uses it directly — `action_run_store.finalize()` (by original design:
its docstring explains the live run store needs a session outliving any
single request, genuinely different from the test fixture's one rolled-back
transaction), plus test-side helpers like `_make_scenario`,
`ensure_test_user_row`, and per-file `_make_daily_challenge` functions
(this is a *widespread* pattern across the suite, not one function) — writes
for real.

**Checked CI separately, so the spec is grounded in what actually exists,
not assumed:** `.github/workflows/ci.yml` runs `pytest -q` with no Postgres
service and no `DATABASE_URL` set at all — CI has always run against
`conftest.py`'s sqlite default exclusively. There is no existing "real
Postgres test database" convention anywhere in this repo today. The
vulnerability is narrower than "tests can hit any database" — it's
specifically "running pytest manually inside an environment where
`DATABASE_URL` was already set to something real before conftest.py loads,"
which in practice today means exactly one thing: running pytest inside a
deployed container.

## Requirement (yours, restated)

Running pytest against a prod-pointed environment must **fail loudly,
immediately, before writing any row** — not silently succeed against
production, and not merely "usually" avoid it.

## Options evaluated

### Option A — isolated test database + hard guard (recommended)

A guard in `conftest.py`, evaluated at **import time** (before pytest
collects or runs a single test), that inspects whatever `DATABASE_URL` is
already present in the environment *before* `setdefault` would apply one,
and refuses to proceed unless it's unambiguously safe:

- **Allowed**: no `DATABASE_URL` set at all (conftest's own sqlite default
  applies), any sqlite URL, or a Postgres URL whose database name matches
  an explicit test-only naming convention (`*_test` suffix) — for the case
  where someone deliberately wants to run the suite against a real
  Postgres instance (catching asyncpg-specific behavior sqlite can't
  surface — not used anywhere today, but worth keeping available
  deliberately).
- **Refused, unconditionally, no override**: the database name exactly
  matches the actual known production name (`breachreplay`) — a small,
  hardcoded denylist as a defense-in-depth backstop, checked *in addition
  to* the naming-convention check, not instead of it. Belt and suspenders:
  the convention check could in principle have a gap; the exact-name check
  can't.
- On refusal: print an unambiguous, specific message (what `DATABASE_URL`
  resolved to, why it was rejected, what to do instead) and `sys.exit(1)`
  before any DB connection is attempted — not a warning, not a skip, a hard
  stop with a nonzero exit code.

**Why this is the primary fix, not Option B:** it's a single, centralized
check that protects every current *and future* test — not just
`finalize()`'s specific bypass. The direct-`AsyncSessionLocal` pattern is
already normal and widespread across this suite (`_make_scenario`,
`ensure_test_user_row`, per-file challenge/streak helpers); Option B only
closes the door `finalize()` uses, leaving every other instance of the same
pattern equally dangerous the next time someone runs pytest somewhere
`DATABASE_URL` happens to be real. This is also the only option that
delivers your stated requirement precisely: a structural refuse-to-run
check *is* "fails loudly instead of writing rows," by construction, for
every write path at once — Option B changes what one function does, but a
new test written six months from now that calls `AsyncSessionLocal`
directly (as several already do, by established local pattern) reopens the
exact same hole with no guard rail stopping it.

**Cost:** zero risk to production code — this only touches `conftest.py` and
runs before any application code executes for real. Doesn't reduce how much
of the suite performs real commits (see Option B below) — it just guarantees
those commits land somewhere safe.

### Option B — inject a session into `finalize()` so tests reuse the rolled-back fixture

Refactor `action_run_store.finalize()` (and similar) to accept a `db:
AsyncSession` parameter instead of opening `AsyncSessionLocal()` internally,
so tests can pass the same rolled-back `db` fixture session everything else
uses, and its writes vanish at teardown like any other test write.

**Why this is real but insufficient alone:** the module docstring explains
*why* `finalize()` opens its own session today — a live, WebSocket-driven
run spans many separate request/message boundaries, each realistically its
own short-lived session in production; unifying that with one long-lived
test-fixture session across an entire multi-step test scenario (many
awaited calls to `apply_verb`, `finalize`, etc., from different points in a
test) is a more invasive change to core live-run session-management
architecture than it first appears, with real risk to production behavior
if done carelessly. And even done perfectly, it only fixes `finalize()` —
every other test helper using `AsyncSessionLocal` directly (the actual
majority of tonight's polluted rows: `_make_scenario`, `ensure_test_user_row`,
`_make_daily_challenge`) is untouched and equally capable of writing to
prod again.

**Worth doing, separately, later:** as a test-quality improvement (faster,
cleaner isolation, one less "real DB required" dependency for this specific
code path) — but not a substitute for Option A, and not this fix.

## Recommendation

**Implement Option A now** (the actual safety requirement — cheap, central,
covers every write path, zero production risk). **Log Option B as a
separate, lower-priority test-quality item** in `docs/BACKLOG.md` once this
spec is acted on — genuinely worth doing, but on its own it wouldn't have
prevented either of tonight's two incidents' *sibling* helpers from doing
the same thing again.

## Implementation notes (for whoever picks this up)

- Guard placement: top of `backend/tests/conftest.py`, before the existing
  `os.environ.setdefault("DATABASE_URL", ...)` line — must run first, since
  the check's whole premise is "what was already set before conftest's own
  default would apply."
- The exact-match prod denylist should be a short, explicit, rarely-edited
  constant (e.g. `{"breachreplay"}`) — not derived from any config or env
  var that could itself be wrong in the same way `DATABASE_URL` was wrong
  tonight.
- Test this guard itself: a small standalone test (or a `pytest_configure`
  hook test run via subprocess, since the guard fires at import time)
  asserting it exits nonzero for a Postgres URL named `breachreplay` and
  passes cleanly for sqlite / a `*_test`-suffixed name.
- Sweep the test suite for every current direct `AsyncSessionLocal` usage
  and confirm each one is now protected by the new guard rather than
  assuming — this spec's whole point is that this pattern is more
  widespread than any one file's docstring currently documents. Checked
  while writing this spec (`grep -rl "AsyncSessionLocal" backend/tests/`,
  excluding `__pycache__`): **9 files beyond `conftest.py` itself** —
  `test_action_run_ws_handler.py`, `test_arena_ai_attacker.py`,
  `test_arena_ai_defender.py`, `test_arena_events.py`,
  `test_arena_spectator.py`, `test_daily_action_mode.py`,
  `test_org_tabletop_regression.py`, `test_phase5.py`,
  `test_scenarios_recent.py`. All 9 are equally exposed today; all 9 are
  covered by Option A's single guard with no per-file changes needed.
