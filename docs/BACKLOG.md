# Backlog

Items identified during active work that are real but explicitly out of
scope for the phase/item in progress when they were found. Not a general
issue tracker — just the small set of things flagged mid-work worth not
losing.

## First EBS snapshot restore drill — wait for DLM's first fire

First EBS snapshot should exist after Sunday 23 August 2026 09:00 UTC
(DLM `policy-0a235e4e35f007629`, daily 09:00 UTC window; AWS starts the
snapshot within that hour) — schedule the first restore drill after that
to validate the backup actually works, not just that the policy is
enabled. Runbook: `docs/EBS_SNAPSHOT_RESTORE_RUNBOOK.md`. Policy was
created manually in the AWS Console, not IaC.

## Phase 4 / ghost racing — leak-safety before build

Spec's "public run = no hidden info" assumption corrected — see spec §6
annotation. Ghost DTO needs its own leak-safety design, not a straight
`action_log` pass-through, especially for Daily's shared-seed spoiler
risk.

**Shipped (selection + DTO, no client playback yet):** server-controlled
ghost DTOs + selection — `GET /daily/ghost` (auth, map-state-only) and
`GET /action-runs/public/ghost/{token}` (Race this run; scenario includes
targets, daily via token stays map-state-only). See
`app/services/action_run_ghost.py` and `tests/test_action_run_ghost.py`.

**Shipped (race start + UI, PR #53):** `POST /action-runs/race` starts a
`mode="scenario"` practice run on the ghost seed (never a second Daily /
leaderboard row). Targets only on `share_token` + scenario-mode ghosts;
`ghost_run_id` is always map-only (Daily entry + defense in depth).

## Phase 3 juice pass — sound, map/feed, public run page, share cards SHIPPED

Spec §5 (`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md`) "Juice pass + share
cards." All five build items have a shipped path; Web Share API (vs
clipboard) is the only leftover share-card nicety.

**Shipped:**
- **Sound — PR #39, merged `59631e9` (2026-08-22).** Three Web Audio cues
  (tick / thud / chime), muted by default, AppShell toggle, persisted in
  `br_sound_enabled`. Silence on miss is intentional.
- **Map/feed animation — PR #40, merged `38c8d64` (2026-08-22).**
  NetworkMap infection pulse, contain ring, node shake; Action Console
  alert feed typewriter. `prefers-reduced-motion` honored. Feed hostname
  leak-safety follow-up in `db26da2` (known-tier gate on incident-feed
  host names).
- **Public run page — PR #41, merged `2608045` (2026-08-22).** Opaque
  share token (Arena-parallel: `POST /action-runs/{id}/share` →
  `GET /action-runs/public/replay/{token}` → `/r/{token}`), not a raw
  `run_id`. Unauthenticated redacted DTO; `SessionReplayScrubber` was
  the wrong shape and was not used. Spec §5 still says `/r/{run_id}`
  and "extend PublicReplayPage with the scrubber" — that line is stale
  relative to what shipped.

**Shipped (this PR):**
- **Share cards — text + PNG/og:image.** Daily-shaped plaintext
  (`🔐` / Score — OUTCOME / Time) now mints from the debrief and points
  at `breachreplay.com/r/{token}` instead of `/daily`. Pillow OG image
  (`GET .../card.png`) from the locked public DTO only; crawler HTML at
  `/public/unfurl/{token}` plus nginx bot rewrite on `/r/{token}` so
  Slack/iMessage/Twitter see `og:image` without executing the SPA.
  Daily never had a host emoji grid on the Action Console card
  (decision-gate `✅❌` is a different path) — not invented here.
  Web Share API still not wired (clipboard is the share action).

**Was:**
- **Share cards.** Daily Wordle-style text already exists
  (`backend/app/api/routes/daily.py` shareable-text builder). Extend
  that pattern to Action Console runs and point the link at
  `/r/{token}`. The PNG / `og:image` renderer (spec: final map thumbnail
  + score + time-vs-real-world + scenario name) is new work, not an
  extension of the Daily text path. One-tap Web Share API / copy-link
  fallback still sits on this item.

## Player-facing moment check — process gap (scan-reveal shipped silent)

Found after the fog-of-war unknown-tier + map-juice work passed leak-safety
tests, the full frontend/backend suites, and an Opus review, then still
shipped with the single most important visual moment disabled:
`NetworkMap` explicitly skipped infect-pulse when `before === "unknown"`,
so `scan_network` resolving silhouettes to known hosts was silent. Unknown
nodes also filled with `colors.void`, so the pre-scan map blended into the
console background. Automated checks were correct about *data* and *not
crashing*; none of them asked whether the player-facing moment actually
played.

That is a process gap, not just a code bug. Do not stand up a heavy visual
QA system to close it. Two lightweight gates would have caught tonight:

1. **Manual playthrough before a juice/fog PR is "done"** (not merely
   mergeable). For Action Console work that touches the map or feed, the
   author (or reviewer) actually starts a run and watches:
   - pre-scan: unknown silhouettes visible against void, unlabeled, no
     edges
   - tap Scan Network: nodes come online (reveal ring / scale), edges
     fade in, names and compromise colors appear — not a pop with no
     motion
   - isolate a host: contain ring
   - a later stage.advance onto a known clean host: infect-pulse along
     an edge
   - run end: debrief, not a frozen console
   If any of those is "I didn't see it," the PR is not done. This is the
   gate that would have caught the skipped `unknown` transition — a human
   looking at the scan, which no unit test of `before !== "unknown"` was
   ever going to fail.

2. **Keep the targeted juice assertions** (the actual automated catch for
   *this* class of miss): unknown → pulsing/compromised/clean must set
   `data-revealing`; unknown disc fill must not be `colors.void`;
   `prefers-reduced-motion` still skips juice. Those live next to
   `NetworkMap.test.tsx`. Do not require a Playwright screenshot CI job
   for the SPA. Backend Playwright is already in this stack for CMMC
   HTML→PDF (`backend/app/services/cmmc_pdf.py`, CI `playwright install
   chromium`) — it has no Action Console session, no WS, no auth cookie.
   Driving a logged-in run for pixel diffs would be a new harness. If a
   later contrast/layout regression needs a picture, a static SVG fixture
   of the three map states (pre-scan / mid-reveal / post-scan) is enough;
   do not screenshot the full console in CI unless that fixture starts
   lying.

**Was / remaining:** the playthrough list above is the safeguard. Not a
Phase 5 item, not a new workflow file — just "look at the moment before
you call the juice done."

## Phase 2.5 — CMMC evidence layer — COMPLETE

Shipped and production-verified 2026-08-07 (spec:
`docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md`). All 8 build-order items
landed: multi-tenancy, consultant/client onboarding, `EvidenceSession`
designation, notification matrix, after-action workflow (lessons/
remediation/dual sign-off), PDF generation (HTML+Playwright), Ed25519
signing/tamper-evidence, consultant branding. A full real end-to-end
walkthrough against production (org bootstrap → invites → two scored
gameplay runs → designation → notification matrix → lessons/remediation/
IRP linkage → dual sign-off → issuance → download → public verification)
found and fixed 4 real bugs, all shipped (`4c207e2`, `88bf357`,
`b2e3d65`). No frontend UI exists for this layer, by design — it's API +
server-rendered PDF only (spec §9: "No compliance language on the play
surface").

This section was left as a stale "not yet scoped" placeholder after the
phase actually completed — corrected here so a future session reading
this file top-to-bottom doesn't re-derive work that already shipped. See
also STATE.md's Phase 2.5 section (same correction) and two related open
items already logged below: "CMMC invitations have no audit trail" and
the Phase 3 items noted in `docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md`
§10 (targeted `escalate`/notification proportionality) and in
"Proportionate Response — CONTAINED_AT_COST is unreachable..." below.

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

## Fog-of-war tone pass (Phase 5) — two-tier unknown/known SHIPPED

**Shipped — PR #35, merged `88ca4bc` (2026-08-22).** Pre-scan hosts are no
longer absent from `run.hosts`. `earned_state_snapshot` sends every
compiled host as an unknown silhouette (`id` + map position +
`visibility: "unknown"`), keyed off the existing `revealed_host_ids`
accumulator — no parallel visibility tracker. `scan_network`'s live delta
is unchanged: the full `_host_summary` node list (hostname/role/segment/
compromise/isolated) in one shot. Unknown hosts are visible but not
clickable. Left the original write-up below as-is for context on how this
was found. The remaining, explicitly deferred work is a separate entry
immediately below (Tier 0).

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

## Fog-of-war Tier 0 — split `scan_network` into an existence reveal — DEFERRED

**Deferred / future. Not started.** Distinct from the two-tier
unknown/known snapshot that shipped in PR #35 (entry above). #35's
unknown silhouettes still sit behind the existing resync/snapshot path;
`scan_network` still returns every host's full field set in one shot.

This item is the original "existence visible before `scan_network` fires"
pre-reveal that was explicitly out of scope for #35: a **Tier 0** at run
start, before any verb fires — dim silhouettes already on the map as a
free (or cheaper) initial reveal of *existence/topology*, with
`scan_network`'s current all-fields response split into partial tiers so
that verb earns compromise/identity rather than host existence. That is a
gameplay-balance change to what `scan_network` actually returns in
`verb_engine.py`, not a UI one. Do not bundle it into a follow-up that
only restyles the unknown tier. Revisit alongside Phase 5's broader tone
pass.

## Action Console mastery signal — per-stage correctness at finalize() — DEFERRED

**Deferred / future. Not started.** Capture per-stage correctness at
`finalize()`, persist separately from `TechniqueEncounter`, feed into
`/mastery/me` without merging incompatible `is_correct` /
`encounter_count` semantics.

Found while investigating why GET `/mastery/me` is empty for Action
Console players after mid-July Item 5: `compute_user_mastery` still reads
`SessionDecision.is_correct` (org tabletop) and `RedTeamMove.succeeded`.
`technique_encounters` (PR #31) is exposure-only — a stage fired,
regardless of containment — and must not be folded into
`attempts`/`correct`/`accuracy_pct`. Pointing `/mastery/me` at encounters,
or naively merging the two, would break Daily Drill weakest-technique
weighting, certs (70% average mastery), admin team skill gaps, and the
profile MasteryBar. Keep dossier = exposure, mastery = graded attempts. A
future Action Console mastery feed needs its own correctness signal (e.g.
whether that stage's host was contained when it fired), not a reuse of
`TechniqueEncounter`.

## CI does not run `tsc -b` / full typecheck; `deploy.ps1` does — DEFERRED

**Deferred / future. Not started.** Consider adding a typecheck step to
CI so a TypeScript error surfaces before deploy, not during it.

Found tonight deploying PRs #31–#36: `chipRefs` callback-ref typing
(`HTMLButtonElement | null` vs `HTMLButtonElement | undefined`) passed
CI (`npm test` / Vitest only — `.github/workflows/ci.yml` never runs
`tsc -b` or `npx tsc --noEmit`) and then failed `deploy.ps1`'s
`npm run build` (`tsc -b && vite build`), blocking the production
cutover. One-line fix shipped in PR #37. Branch protection's required
checks are locked to exactly `["review", "test"]`; a typecheck belongs
in the existing `test` job (same pattern as the frontend Vitest steps)
so it does not need a new required check name.

## Frontend test coverage — no runner configured — FIXED

**Fixed on branch `frontend-test-infra`.** Added Vitest + React Testing
Library (`frontend/vitest.config.ts` merges the real `vite.config.ts`;
`frontend/src/test/setup.ts` registers `@testing-library/jest-dom/vitest`
matchers + a jsdom `matchMedia` polyfill `NetworkMap.tsx` needs).

An initial smoke-test layer, not full coverage — 11 tests across 6 files
covering the app's major surfaces: `NetworkMap.test.tsx`,
`ActionConsole.test.tsx`, `AppShell.test.tsx`, `DailyBreachPage.test.tsx`,
`ScenarioLibraryPage.test.tsx`, `LandingPage.test.tsx`. Each renders
without crashing and exercises one real interaction (a verb-chip tap
calling `submitVerb`, the mobile nav drawer toggling, a scenario launch
POSTing to `/action-runs`, etc.) with `axiosInstance`/`api`/`useRunSocket`
mocked rather than hitting real network or WebSocket connections. No
CMMC evidence-pack UI test — confirmed none exists (see the Phase 2.5
entry above).

Wired into `ci.yml`'s existing `test` job (frontend steps run after the
existing pytest steps, same job — not a new one) rather than adding a
new job + a new required branch-protection check: branch protection's
required checks are locked to exactly `["review", "test"]`, and
`claude-review.yml` already polls/trusts a check named `test` as
independent evidence. This gets frontend coverage into the exact same
gate backend PRs already go through with zero changes to
`claude-review.yml` or branch-protection settings.

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
the fog-of-war Tier 0 entry above, which is the remaining adjacent work;
the two-tier unknown/known snapshot itself has shipped).

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

## Arena technique coverage — three attacker tags lack dossier entries

Arena's `_ACTION_TECHNIQUE_IDS` maps six attacker action types to MITRE IDs,
but only three (`T1078`, `T1068`, `T1486`) have entries in `TECHNIQUE_DOSSIER`
today. Arena match completion therefore filters credit to those three only —
no parent/sub-technique normalization (e.g. forcing `T1003.001 → T1003` would
misattribute Colonial-Pipeline-specific incident narrative to a synthetic
Arena match). The remaining three need new dossier entries authored to the
same real-citation bar as the original 30 before Arena can credit them:

- **T1046** (network discovery) — `discover_segment` / `discover_host`
- **T1550.002** (Pass the Hash) — `lateral_move`
- **T1003.001** (LSASS credential dump) — `dump_credentials`

Not authoring now; tracked here so Arena dossier writes don't silently skip
these forever.

## Notification matrices remaining — MGM, Colonial, NHS (items 3–5/5)

SolarWinds (item 1/5, migration `0038`) and Log4Shell (item 2/5, migration
`0042_log4shell_notification_matrix`) are authored. Mechanism needs no further
code changes — remaining work is content + a per-scenario backfill migration
matching Log4Shell's shape. Party lists must stay scenario-native (not the
DIB/DC3 template):

- **MGM** — PCI / card brands, FBI, guest notification, SEC 8-K; extract from
  `mgm-gate-005` / `mgm-pressure-004`
- **Colonial** — TSA / NERC CIP / CISA / FBI; thinnest seed extract, most
  citation research
- **NHS WannaCry** — ICO / NCSC / NHS England; extract from `nhs-gate-005` /
  pressures (availability vs personal-data-breach judgment already authored)

Rough content estimate for the three: ~1.5–2 focused days (see session
scoping 2026-08-23).

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

## Proportionate Response — CONTAINED_AT_COST is unreachable on at least two flagship scenarios — FIXED for all five flagship scenarios

Discovered while building a demo CMMC evidence pack: tried to script a
Colonial Pipeline run that lands on `contained_at_cost` specifically (to
show a non-trivial-but-not-egregious operational-impact section) and
found it's mathematically impossible given the actual scoring code, not
just hard to hit by chance.

The math (`app/services/verb_engine.py`): `GRACE_FLOOR_WRONG_ISOLATIONS
= 1` (the first wrong isolation is always free — `contained` regardless
of ratio), `OVERREACTED_COVERAGE_THRESHOLD = 0.6` (wrong_isolated /
decoy_pool). `contained_at_cost` requires wrong_isolated > 1 (past the
grace floor) AND coverage_ratio <= 0.6. For that band to exist at all,
decoy_pool must be >= 4 (the smallest wrong_isolated past the grace
floor is 2, and 2/4 = 0.5 is the first ratio that clears the floor
without also exceeding the overreacted threshold).

**Root cause traced to `host_harvest.build_host_plan`** (not the scoring
constants themselves): `decoy_count = max(ceil(harvested*PADDING_RATIO),
archetype_roll - harvested)`. Colonial's `energy_utility` archetype had
`host_count_range=[12,15]` and SolarWinds fell back to
`small_healthcare`'s `[8,10]` — in both cases the archetype-roll term's
ceiling sat so close to the scenario's own harvested-host count that the
padding-ratio floor term almost always won, pinning the decoy pool below
4 on effectively every seed, regardless of the scoring thresholds.

**Fix (Option A from the list below — content, not scoring):**
- First attempt was simpler than what shipped: just raise
  `energy_utility.host_count_range` directly. Reverted immediately —
  `ORG_ARCHETYPES` is Arena mode's own live archetype universe
  (`arena_matchmaking_service.py`'s `secrets.choice(list(ORG_ARCHETYPES
  .keys()))` for real match archetype selection, plus admin/arena API
  validation and every Arena AI-difficulty test sweep), not just a
  decision-gate sizing knob. Bumping it broke
  `test_difficulty_produces_measurably_different_outcomes_same_seed`
  (hard bot's win rate fell below easy's on the bigger map within the
  fixed step cap) — a real Arena balance regression, not a test
  artifact, and it would have silently widened production Arena's
  matchmaking pool with an untuned map size.
- Shipped instead: a **separate** `DECISION_GATE_ARCHETYPES` dict
  (`org_simulation.py`), consulted only by
  `action_engine.compile_scenario` via a private merged lookup
  (`_COMPILE_SCENARIO_ARCHETYPES = {**ORG_ARCHETYPES,
  **DECISION_GATE_ARCHETYPES}`) — `ORG_ARCHETYPES` itself stays
  byte-identical to its original two entries, so Arena's matchmaking,
  API validation, and test sweeps never see the new keys.
  - `energy_utility_flagship` (`host_count_range=[16,20]`) — what
    Colonial Pipeline's `industry_vertical: "energy"` now maps to,
    giving the archetype-roll term real headroom over its 7 harvested
    hosts.
  - `technology_saas` (`host_count_range=[12,15]`) — what
    `industry_vertical: "technology"` now maps to, instead of
    SolarWinds/Log4Shell silently falling back to `small_healthcare`.
    That fallback had a side-effect bug too: it pulled in
    `small_healthcare`'s `"healthcare"` industry_vertical for
    `_SEGMENT_NAME_POOLS` purposes, giving tech companies a "clinical"
    network segment. `technology_saas` has no authored segment-name pool
    yet, so it correctly falls through to `_SEGMENT_NAME_POOLS["default"]`
    (`["corp", "dmz", "server"]`).
  - Log4Shell also carries `industry_vertical: "technology"` and picks
    up `technology_saas` as a side effect of the new mapping — checked,
    not a regression: its decoy pool moves from a constant 6 (old
    archetype) to 7-10 (new), strictly better, never worse.

Re-verified empirically post-fix, 1000 seeds each, using the exact
`decoy_pool = total_hosts - attack_path_hosts` computation
`determine_outcome` actually uses:

| Scenario | decoy_pool distribution (1000 seeds) | `contained_at_cost` reachable |
|---|---|---|
| Colonial Pipeline | {4:201, 5:182, 6:202, 7:193, 8:222} | **1000/1000** |
| SolarWinds | {4:262, 5:228, 6:262, 7:248} | **1000/1000** |
| Log4Shell | {7:262, 8:228, 9:262, 10:248} | 1000/1000 (already was) |
| NHS WannaCry | {8:1000} | 1000/1000 (already was, untouched) |

**MGM Resorts follow-up — also FIXED**, same pattern. MGM was different
from Colonial/SolarWinds in one respect worth recording: it only
harvests **1** literal hostname (`BACKUP-VEEAM-01`), so the padding-ratio
floor (`ceil(1*0.2)=1`) was never the binding constraint the way it was
for Colonial/SolarWinds. What actually pinned MGM's decoy pool was that
`_attack_path_host_ids` resolves to a **constant 5 hosts** regardless of
`total_hosts` (confirmed empirically across 200 seeds — role-based attack
targeting, not tied to the 1 harvested hostname), so `decoy_pool =
total_hosts - 5` directly. Under `small_healthcare`'s `[8,10]` range, a
roll of 8 gives `decoy_pool=3` — 32% of a 1000-seed sample landed there.

Fixed the same way as Colonial/SolarWinds: a new `hospitality_resort`
entry in `DECISION_GATE_ARCHETYPES` (`host_count_range=[9,12]`), mapped
from `industry_vertical: "hospitality"` (confirmed via grep to be
authored by MGM only — no collision risk with other content).
`ORG_ARCHETYPES` itself remains untouched — re-verified byte-identical to
its original two entries (`small_healthcare`, `energy_utility`) after
this change too. Re-verified empirically, 1000 seeds: MGM now reaches
`CONTAINED_AT_COST` on **1000/1000** seeds (was 680/1000). All five
flagship scenarios are now fully reachable.

Original three options considered (kept for record — (1) is what
shipped for all five scenarios; (2) and (3) remain on the table for any
future scenario that hits this same ceiling):
1. **Content fix** — raise the archetype's `host_count_range` (or give
   the scenario its own archetype) so the roll term dominates the
   padding floor. Shipped for Colonial/SolarWinds/MGM above.
2. A grace floor and/or `OVERREACTED_COVERAGE_THRESHOLD` that scale with
   decoy pool size instead of flat constants — algebra worked during
   this investigation shows floor-scaling alone can't fix a pool of 2-3
   (the only wrong_isolated value past any nonzero floor already implies
   ≥67% coverage), so this would need both constants to become
   pool-size-aware together — a bigger, riskier change to scoring math
   shared by every scenario. Not pursued once (1) proved sufficient.
3. Accept that some scenarios are inherently pass/fail on proportionality
   given their map size, and say so explicitly somewhere a player/assessor
   can see it. Not needed — (1) fixed all five flagship scenarios; still
   the fallback approach if a future scenario hits this same ceiling and
   a dedicated archetype isn't a good fit.
