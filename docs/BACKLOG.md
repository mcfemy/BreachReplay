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

Found during Item 5 planning. STATE.md's Item 5 line says
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

**Fixed — `b17404c`.** Sidebar now collapses below the `md:` breakpoint
instead of eating the viewport. `PHASE2_ACCEPTANCE.md` criterion 8 (phone,
one thumb) is marked PASS. Left the write-up below as-is for context on
how it was found.

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

This matters beyond a nitpick: PHASE2_ACCEPTANCE.md's criterion 8 requires
"phone-with-one-thumb playability" before declaring Phase 2 done — that
gate cannot pass while AppShell doesn't collapse. Fixing it (a collapsible/hamburger sidebar
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

**Fixed — migration `0031_scenario_is_synthetic`.** `Scenario.is_synthetic`
is now a real structural flag, not a title match (fix #1 below); the
picker filters on it (`daily.py:233`). 323 pre-existing leaked rows
remediated. Fix #2 (isolated test DB instead of the shared dev DB) landed
separately — see `docs/TEST_DATABASE_SAFETY_SPEC.md` and
`backend/tests/conftest.py`'s `_refuse_unsafe_database_urls()`. Left the
write-up below as-is for context on how it was found.

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

## `process_name`-keyed hidden IOCs have no reveal mechanism (username half fixed 2026-07-25)

Found while specing the host-namespace-unification fix
(`docs/HOST_NAMESPACE_UNIFICATION_SPEC.md`) — a distinct, more severe bug
than that spec's own subject, surfaced by the same investigation but
explicitly out of that spec's scope. `verb_engine.py`'s full verb switch
had exactly one value-based IOC pivot: `block_ip`, matching
`matches_on.get("ip") == target` regardless of which host the IOC
physically landed on. There was no equivalent for `matches_on["username"]`
or `matches_on["process_name"]` — `reset_creds` looked like it should be
the username case; it wasn't, it matched against `world.credentials` (a
different data structure) and disabled a credential without ever touching
`discovered_ioc_keys`.

**2026-07-25: the username half is fixed.** `reset_creds` now also checks
`ioc_placements` for a `matches_on["username"]` match and reveals it,
mirroring `block_ip`'s pattern exactly — the two effects (credential
disable, IOC reveal) are independent and can both fire from one call. See
`docs/HOST_NAMESPACE_UNIFICATION_SPEC.md`'s 2026-07-25 update, which also
declares "containment verbs double as value-pivots" a deliberate
convention for any future verb, not a one-off. Covered by
`test_reset_creds_reveals_a_username_keyed_ioc_by_value_alongside_the_credential`,
`test_reset_creds_reveals_a_username_keyed_ioc_with_no_matching_credential`,
`test_reset_creds_username_answer_is_discoverable_through_legitimate_play`,
and `test_reset_creds_wrong_guess_penalty_matches_block_ip_exactly` (all in
`test_verb_engine.py`), plus a playability regression guard
(`test_scenario_content_playability.py`) asserting every username/ip-keyed
IOC's value is actually readable in the visible alert feed across all 5
flagship scenarios — both already passed without content changes.

**`process_name` remains the open half.** MGM Resorts' scenario has 2 IOCs
keyed on it (`RMM`, `BACKUPWIPE`) still reachable only by
`query_logs`/`image_disk`-ing the exact (procedurally-named, unguessable)
host they landed on — no value-based shortcut exists for this
`matches_on` type yet. Needs its own verb (or a generalized target) per
the now-declared convention above; deliberately not done alongside the
username fix since only 2 IOCs across all 5 flagship scenarios currently
need it — worth adding once a second scenario actually leans on
process-name signatures, not preemptively.

## MGM Resorts needs real hostnames — content pass, blocks collateral-weight authoring

Found while speccing "Proportionate Response" (outcome grading + collateral
cost, see that spec for full context). All 10 of MGM's hosts are named
`BACKUP-VEEAM-{NN}` — one undifferentiated pattern, no signal
distinguishing "this is the reservation system" from "this is a random
backup target." Every other flagship scenario's harvested hostnames
(Colonial's `OT-HISTORIAN-01`, SolarWinds' `adfs-01.corp.internal`,
NHS's `NHS-PACS-01`) carry enough real-world specificity to author
per-host collateral weights against; MGM's don't, and inventing
distinctions the content doesn't support is exactly the fabrication the
provenance rule (same discipline as `hidden_iocs`) forbids.

The real incident (Scattered Spider, 2023, via vished helpdesk social
engineering into ALPHV/BlackCat ransomware) is well documented as hitting
reservation, loyalty-program, and casino-floor systems specifically —
real hostnames reflecting that (property-management-system, slot-network,
key-card-server, loyalty-db, etc.) would give this scenario's map the
same narrative weight the other four already have, and unblock
collateral-weight authoring for it. Until this lands, MGM's collateral
weights stay unauthored — Proportionate Response ships for the other four
scenarios first.

## NHS WannaCry: legacy/unpatched hosts are decoys, but that's backwards

Found in the same pass. `NHS-LEGACY-XP-03` and `NHS-SERVER-LEGACY-08` sit
in the compiled decoy pool (never appear in any stage's
`compromises_host_ids`) — but "unpatched legacy Windows, notably XP" is
*the* documented root-cause vulnerability class in the real 2017 WannaCry
incident, not incidental flavor. A player who reasons correctly from the
real incident and isolates exactly those hosts is isolating hosts the
game currently scores as pure collateral — the game penalizing a player
for knowing the actual history is the worst failure mode available here,
worse than not rewarding it. Worth a scenario-content look at whether
these two should be on the attack path instead of padding. Filed
separately from Proportionate Response, not blocking it — NHS's other
decoys (PACS, domain controller, ortho/lab workstations) are sourced
enough to author weights for now.

## PRIORITY: Final-stage target is unbound from real content in 3 of 5 flagship scenarios

**Higher priority than the other two entries above.** The single host a
player must isolate to win — the most important host in the entire
incident — has no tie to the real breach in 3 of 5 flagship scenarios.
That cuts against the provenance discipline this whole content model is
built on, and it cuts at the exact point that matters most. The MGM
hostname pass and the NHS legacy-host placement question are real but
narrower; this one should get attention sooner, not batched in behind
them.

Found while resolving how to key `collateral_weights` stably across seeds
(scenario mode uses `secrets.randbelow` — a genuinely random seed per
playthrough, see `action_runs.py`). Compiled Colonial Pipeline, SolarWinds,
Log4Shell, MGM, and NHS across 5 different seeds each and checked whether
the final stage's `compromises_host_ids` target is one of the scenario's
own `host_harvest.harvest_hostnames()` — the real, author-cited names
(`OT-DC-19`, `CORP-HISTORIAN-*`, `BACKUP-VEEAM-*`-style) vs. procedurally
generated padding.

**Log4Shell and NHS: final target is the same real, harvested hostname on
every seed** (`app-svr-07.prod.internal`, `NHS-LAB-SRV-01`) — stable and
narratively grounded. **Colonial Pipeline, SolarWinds, and MGM: the final
target is a procedurally generated hostname on every seed tested, and a
*different* one each time** — the win condition's own target host has no
fixed identity tied to the scenario's authored content at all for these
three. A player who reads Colonial's real story and reasons "the pipeline
OT domain controller is what actually matters" is isolating a stably-named
host (`OT-HISTORIAN-01` or similar) that may or may not be anywhere near
whatever randomly-named host the engine actually picked as this run's
final target.

This is a `host_harvest`/`action_engine` stage-to-host binding question
(likely `_build_stages`'s `preferred_host_ids` matching not being
constrained to prefer harvested hosts for the final gate specifically),
not something Proportionate Response's collateral-weight authoring can
paper over — filed separately. Worked around for now by keying
`collateral_weights` on hostname and restricting authored entries to each
scenario's actual `harvest_hostnames()` set; procedural hosts (including,
for these three scenarios, the final target itself) get the flat default
weight rather than a fabricated citation.

## NHS WannaCry's final-stage trigger makes OVERREACTED effectively unreachable

Found during Proportionate Response's post-deploy browser verification
(390px click-through of the OVERREACTED/CONTAINED debrief states). NHS's
final stage fires at `trigger_seconds=210`, and `BREACH_HEAD_START_SECONDS`
(90) is already baked into the attacker clock at t=0 — leaving only ~120s
of real elapsed time before the final stage fires regardless of seed
(trigger timing comes from the authored decision_tree/pressure_injection
timestamps + `compression_ratio`, both scenario-level constants, not
seed-dependent). One `scan_network` (45s) plus the mandatory final-target
`isolate` (20s) already spends over half that window, leaving room for at
most 2-3 more isolates. NHS's decoy pool is 8 hosts — reaching the 60%
coverage threshold (`OVERREACTED_COVERAGE_THRESHOLD`,
`verb_engine.determine_outcome`) needs 5+. The math doesn't fit: a player
would have to isolate 5 of 8 decoys in roughly 55-75s of remaining budget,
which isn't achievable through the UI's tap-to-target flow.

Practical effect: NHS can still land on `contained`, `contained_at_cost`,
`breached`, or `breached_spread_limited` normally, but `overreacted`
specifically — stopping the target while isolating most of the map — is
not reachable in practice for this scenario. Confirmed by direct
demonstration: an isolate-everything attempt against NHS landed on
`contained_at_cost` (2 of 8 decoys isolated before the run ended), not
`overreacted`; the equivalent attempt against Colonial Pipeline (367s
trigger, only 2 decoys) reached `overreacted` cleanly.

Not necessarily wrong on its own terms — WannaCry was a genuinely
fast-moving worm, and a tight response window is arguably in-fiction
correct for this specific incident. But it means one of the five states
Proportionate Response added is partially inert for this scenario: the
grading logic is fine, there just isn't enough real time inside NHS's
authored pacing to ever land there. Worth a look in the Phase 3 tuning
pass — either NHS's pacing is intentionally this tight and that's fine as
is, or the compression/head-start interaction deserves a per-scenario
adjustment. Not a bug to fix now, a design question to revisit deliberately.

## Arena mode doesn't share the Action Console's new surfaces

Deliberate isolation from Phase 2 Item 3 onward — Arena and the solo Action
Console have always been separate code paths (REVIEW_CRITERIA.md's org-
tabletop isolation rule (d) cites Arena's own prior isolation as the
precedent it follows) — but it means the two modes now teach differently.
Neither Proportionate Response's 5-state grading nor diegetic tool output
reached Arena; both are Action Console-only. Assessed scope for each
before filing this, rather than assuming either is a quick port:

**Outcome grading — large, not a rename.** Arena's terminal result is a
hard boolean, decided in `_mark_match_completed_if_needed`
(`backend/app/websocket/handlers.py:620`): attacker wins if
`global_flags["impact_deployed"]`, defender wins if
`check_defender_containment` passes after a minimum action count, defender
wins by default if the match hits `_MAX_MATCH_ACTIONS` unresolved. That
feeds directly into an ELO rating update
(`arena_rating_service.compute_new_ratings`, K_FACTOR=32) in the same
transaction. There is no scored breakdown and no collateral/proportionality
signal computed anywhere in `org_simulation.py` or the handler — introducing
`contained_at_cost`/`overreacted`-equivalents would mean inventing a new
metric (e.g., unnecessary isolations, over-broad `increase_monitoring`)
from `OrgState` that doesn't exist today, then deciding how a 5-state
outcome coexists with (or replaces) the ELO win/loss feed the whole rating
system depends on. `ArenaDebriefPage.tsx:267-269` still renders the raw
`match.status` enum ("attacker won" / "defender won") and doesn't reference
`useRunSocket.ts`'s `OUTCOME_LABELS` map at all — cosmetic relabeling alone
would be trivial; making the labels mean something the way they do in the
Action Console is new game-design work, not a port.

**Diegetic tool output — also large, different action vocabulary.** No
`tool_output` hook exists anywhere in Arena's path (confirmed: zero
references outside `verb_engine.py`/its tests). Arena's only per-action
feedback today is the alert feed (`ArenaMatchPage.tsx`) — detection-rule
flavor text for the *observer*, not tool-rendered output for the *actor*.
Arena's action vocabulary is also materially different from the console's
8 verbs: 12 action_types across two roles (`org_simulation.py:427-459`) —
attacker `discover_segment/discover_host/gain_foothold/dump_credentials/
escalate_privilege/lateral_move/deploy_impact`, defender `isolate_host/
disable_credential/patch_host/increase_monitoring/acknowledge` — only
loosely overlapping the console's verbs (`isolate_host`≈`isolate`,
`patch_host` has no console equivalent, and Action Console has no
attacker-side actions at all). `tool_output.py`'s renderers are keyed to
the console's exact 8 payload shapes; reuse here means writing ~12 new
renderers for two roles, not pointing Arena at the existing module.

Not proposing either for the current phase. Worth scoping properly as a
real Phase 3+ project — likely its own spec, not a follow-on task to either
Proportionate Response or diegetic tool output — given both would need new
game-design decisions (what collateral means for a live PvP match; what
"real tool output" means for attacker-side actions like credential
dumping), not just code reuse.

## CMMC invitations have no audit trail — Redis-only, no DB row

Flagged by Femi during item 2 (onboarding/invitation flow) design review.
`app/services/cmmc_invites.py` stores invite tokens purely in Redis
(`cmmc_invite:{token} -> JSON`, TTL via `CMMC_INVITE_EXPIRE_MINUTES`,
deleted on redemption) — the same pattern as password-reset tokens. This
satisfies every requirement actually asked for (email-bound, single-use,
expiring) but means there is no way to answer "who invited whom, and
when" once a token is redeemed or expires unredeemed — the payload is
gone. For a product whose whole value proposition is compliance evidence,
that gap may itself matter eventually (an auditor asking how a given
client_participant got access, or a consultant_admin wanting to see/
revoke their org's pending invites).

Not fixed now because nothing in `PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md`
or the approved item-2 design asks for invite listing, revocation, or
audit history — building it speculatively would be scope beyond what was
requested. If it's ever needed: add a lightweight `Invitation` DB row
(token hash, not the raw token; email; role; org id; invited_by_user_id;
created_at; redeemed_at nullable) alongside the existing Redis token
rather than replacing it — Redis stays the fast single-use/expiry check,
the DB row becomes the audit/list/revoke surface.

## Issued evidence packs: single-EC2-instance storage, no off-site backup

Flagged by Femi during item 7 (signing/tamper-evidence) design review.
`app/services/cmmc_issuance.py` writes each issued, signed PDF to
`ISSUED_PACKS_DIR` once, at issuance, and serves those exact bytes on
every subsequent download — deliberately never re-rendered, since a
future Chromium/Playwright upgrade re-rendering the same session could
silently produce different bytes than what was actually signed.

Item 7 added a Docker named volume (`issued_packs_data`, `docker-
compose.prod.yml`) so this storage survives an ordinary redeploy — before
that fix, it would NOT have: `docker inspect` on the production `backend`
container showed zero volume/bind mounts, and `docker compose up -d
--build` recreates the container from a fresh image on every deploy, so
anything written to a bare in-container directory is destroyed the
moment the container is torn down. The volume fixes that specific,
otherwise-fatal problem.

What the volume does NOT fix: it's still a single EC2 instance's local
EBS volume. Instance termination, EBS volume loss/corruption, or
accidental `docker volume rm` all still mean permanent, unrecoverable
loss of a legally/compliance-significant signed document with no way to
regenerate an identical replacement (the whole point of signing is that
"identical" is exactly what can no longer be reconstructed after the
fact for a session whose data may have since changed). S3 (versioned,
cross-AZ replicated) is the real eventual answer — not built now because
nothing about the current, low issuance volume makes it urgent, and it
adds real complexity (credentials, a new dependency, a migration path
for whatever's already been issued by the time it's built).

## `app/uploads/` (ingestion feature) durability — FIXED, and the original note here was imprecise about which directory was actually live

Discovered as a side effect of investigating the issued-packs durability
question above, initially logged as a hypothesis pointing at
`backend/app/uploads/`. Follow-up investigation (before building the fix,
not after) corrected that: `backend/app/uploads/` is **gitignored**
(`.gitignore:119`, confirmed via `git ls-files` — zero tracked files) and
**not read by any current code path** — `ingestion.py`/`orgs.py` both
resolve their upload directory via `os.environ.get("UPLOAD_DIR",
"/tmp/breachreplay_uploads")`, and `UPLOAD_DIR` was never set in
`.env.prod`. The Jul-24-dated files sitting in `backend/app/uploads/` on
the EC2 host are a dead, pre-refactor artifact — never deleted (not git-
tracked, so `deploy.ps1`'s rsync never touches it either way) and quietly
re-baked into every image via `COPY . .` (which copies whatever exists in
the build context regardless of gitignore status), but genuinely inert:
confirmed zero `BreachDocument`/`Scenario` rows reference any file under
it, and zero rows reference a `/tmp/breachreplay_uploads` path either
(the ingestion feature has apparently never been used against production
yet). Checked directly rather than assumed, given the difference between
"dead legacy directory" and "live feature losing real data" matters.

The REAL live path, `/tmp/breachreplay_uploads`, had the defect: `docker
inspect` confirmed zero volume/bind mounts on `backend`, and `/tmp`
inside a container is part of its ephemeral writable layer — wiped on
every restart, and (unlike `backend/app/uploads/`) never protected by
the rsync-exclude/image-rebuild cycle either, since it sits outside the
git-tracked source tree entirely. Confirmed empty immediately after a
real redeploy.

**Fixed**: same named-volume pattern as `issued_evidence_packs` (item 7)
— a new `uploads_data` Docker volume mounted at `/app/uploads_data`
(`docker-compose.prod.yml`, `backend` service only — `worker`/`beat`
never serve upload routes), `mkdir -p /app/uploads_data && chown -R
appuser:appuser` in `Dockerfile.web` (fresh volumes mount root-owned
otherwise — the exact bug hit and fixed during item 7's own
verification), and `UPLOAD_DIR=/app/uploads_data` set in `.env.prod`. No
application code changes needed — `ingestion.py`/`orgs.py` already read
`UPLOAD_DIR` from the environment correctly; this was purely an infra
gap. Verified surviving a real redeploy the same way `issued_packs_data`
was. The dead `backend/app/uploads/` directory and its 20 orphaned files
are unaffected and still gitignored/unreferenced — not cleaned up as
part of this fix, since removing committed-adjacent server state
unilaterally is a separate, lower-stakes decision, not a durability
question.
