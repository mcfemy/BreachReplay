# BreachReplay: From Gamified Demo to Formidable Learning Platform

Phased implementation plan. Each phase is self-contained enough to execute in a fresh
chat context via `/do`. Do not skip Phase 0 context when resuming — it contains the
exact schemas/endpoints every later phase depends on.

## The wedge (why this can be #1, not just "more features")

Existing platforms (TryHackMe, Immersive Labs, RangeForce) are either pure technical labs
(no incident-command pressure) or pure tabletop narrative (no real telemetry). BreachReplay
already uniquely combines: (a) real-incident decision trees sourced from actual breach
disclosures (CISA advisories, SEC 8-Ks) with real IOCs/log lines, (b) a dual-mode
red/blue adversarial loop in one product, (c) multiplayer incident-command role-play
with a live pressure-injection layer (executives calling mid-crisis). Nobody else has
all three. The plan below does NOT dilute this with generic LMS features — it closes
the 8 credibility gaps while doubling down on real-incident fidelity and the red/blue
dual-mode as the differentiator, and turns the two adversarial modes into a shared
skill-graph so red-team and blue-team play build the same underlying competency profile.

## Phase 0 — Documentation Discovery (completed, condensed)

**Allowed APIs / confirmed patterns (do not deviate without re-verifying):**

- ORM base: `from app.db.session import Base` (single source, `backend/app/db/session.py`).
  All models: `String` UUID PKs via `default=lambda: str(uuid.uuid4())`.
- New models MUST be added to `backend/app/models/__init__.py` (`__all__` list) or
  Alembic autogenerate / `env.py`'s `Base.metadata` won't see them.
- Migration head is `0016_mfa_saml` (verify with
  `grep -rn "down_revision" backend/migrations/versions | grep -v "0016\|0015\|0014"`
  before writing a new migration — head may move if other work lands first).
  Revision ID convention is inconsistent (some files use full filename stem, some short
  numeric) — always match whatever string the *current* head file uses for `revision`.
- JSON/list column idiom: `JSONB().with_variant(JSON, "sqlite")` for dict blobs,
  `ARRAY(String).with_variant(JSON, "sqlite")` for string-list columns (note the `()`
  difference — JSONB is instantiated before `.with_variant`, ARRAY is not).
- `server_default` idiom: string literals for scalars (`server_default="0"`), `sa.text("NOW()")`
  for timestamps.
- `get_db()` is a no-arg async generator FastAPI dependency (`app/db/session.py`).
- Auth: `get_current_user` (JWT `sub` claim → DB lookup, no other claims embedded) and
  `require_admin` (role in `owner`/`admin`) are the only two auth dependencies that exist.
  There is **no org-scoped or team-scoped permission dependency** — every admin.py handler
  manually filters by `current_admin.organization_id` inline. Any cohort/instructor
  permission needs a new dependency, not an extension of an existing one.
- Frontend: React 19 + react-router-dom v7 + TanStack Query v5 + Zustand v5 (plain
  `create()`, no middleware) + Tailwind v3 (custom `breach-*` palette in
  `tailwind.config.js`, dark monospace terminal aesthetic, `#0a0e1a` bg). **No chart
  library, no icon library (emoji only), no animation library** — all data-viz is
  hand-rolled inline SVG (see `AdminDashboardPage.tsx` ~L790-860 sparkline for the
  house pattern to copy). `animate-bounce-in` in `XPToast.tsx` is currently dead
  (undefined in Tailwind config) — fix this while touching that file, don't add new
  undefined animation classes.
- API client: `frontend/src/lib/api.ts` — `axiosInstance` with bearer-token injection +
  401 refresh-rotation interceptor already handles error normalization. New frontend
  code should use the existing `api.get/post/patch` wrapper, not raw `fetch` (two pages —
  `AdminDashboardPage.tsx` upload and `OrgUploadPage.tsx` — already deviate with raw
  `fetch` for multipart; don't add a third pattern).

**Critical existing-code facts that shape the plan (from full reads, not assumed):**

1. `backend/app/api/routes/redteam.py`: `succeeded = random.random() < base_success` —
   pure RNG, confirmed root cause of "child's play" perception.
2. `backend/app/models/session.py` `SessionDecision` table already stores
   `nist_control_ref` and `mitre_technique` **per answered gate**, and
   `backend/app/models/red_team.py` `RedTeamMove` already stores `technique_id` per
   move. **Nobody aggregates these into a mastery view today** — this is pure query
   work, no new source-of-truth columns needed for v1 mastery tracking.
3. `backend/app/api/routes/sessions.py` scoring: `team_score = decisions_correct /
   decisions_made * 100` — flat, no difficulty/time weighting despite
   `response_time_seconds` being captured and unused.
4. `backend/app/pipeline/tasks.py` `_build_fallback_debrief`'s `mitre_coverage` is
   **fake** — it splits `scenario.mitre_techniques` in half by array position, not by
   which gates the team actually answered. Real bug, not just a gap — fix in Phase 1.
5. `backend/app/api/routes/admin.py` `/admin/compliance-analytics` already computes a
   readiness score, NIST/MITRE coverage %, per-analyst accuracy, and scenario
   calibration — this is more mature than a first pass suggested. Phase 6 extends this
   endpoint; it does not replace it.
6. `backend/app/models/team.py` `Team`/`TeamMember` is flat, self-service (join/leave),
   XP-pooling only — no assigned membership, no cohort concept, no instructor role.
   Phase 6 adds assignment on top of this, it does not redesign Team.
7. `backend/app/services/cert_service.py` — 8 certs, criteria are simple thresholds
   (session count, avg score, XP, streak) via raw SQL in `check_and_award_certs`, no
   anti-farming, no capstone. Already-issued certs (real user data) must not be
   silently invalidated when Phase 5 tightens criteria — new criteria apply
   prospectively; existing rows are grandfathered explicitly (see Phase 5 guard).
8. WebSocket `decision_gate` event never actually sends `countdown_seconds`/
   `urgency_level` despite the frontend type expecting them — timer is cosmetic only,
   nothing auto-resolves a gate on timeout. Flagged for Phase 3, not fixed incidentally
   elsewhere.

---

## Phase 1 — Competency & Mastery Engine (foundation, do this first)

**Why first:** highest leverage, lowest risk. Purely additive (new endpoints + one
small new frontend surface), no changes to existing gameplay, and it fixes a real bug
(fake `mitre_coverage`) while it's here.

**What to implement:**

1. New backend module `backend/app/services/mastery_service.py`:
   - `compute_user_mastery(db, user_id) -> dict` — one query over `SessionDecision`
     (group by `mitre_technique`, count total vs `is_correct`) UNION with one query
     over `RedTeamMove` (group by `technique_id`, count total vs `succeeded`), merged
     by technique code into `{technique_id: {attempts, correct, accuracy_pct, source: "blue"|"red"|"both"}}`.
   - `compute_user_nist_mastery(db, user_id) -> dict` — same pattern grouped by
     `nist_control_ref` (blue-team only; red team has no NIST ref today).
   - `compute_session_mitre_coverage(db, session_id, scenario) -> dict` — replaces the
     fake fallback logic: `techniques_exercised` = distinct `mitre_technique` from that
     session's `SessionDecision` rows; `techniques_missed` = `scenario.mitre_techniques`
     minus exercised. Real, not positional-split.
2. Wire the real coverage function into `backend/app/pipeline/tasks.py`
   `_build_fallback_debrief` (replace the `mitre_techniques[:len//2+1]` split) — this
   is the bug fix riding along with the feature.
3. New endpoint in a new `backend/app/api/routes/mastery.py`:
   `GET /mastery/me` → `{technique_mastery: {...}, nist_mastery: {...}, weakest_techniques: [...top 5 by lowest accuracy with attempts>=1...]}`.
   Register router in `backend/app/main.py` alongside existing routers (copy the
   registration pattern used for `redteam.py`'s router — same file, find the
   `app.include_router(...)` block).
4. Frontend: new `frontend/src/pages/MasteryPage.tsx` (or a section added to
   `UserProfilePage.tsx` — prefer adding a section there first since it's lower
   surface area than a new route; only split into its own page if the profile page
   gets crowded). Render per-technique accuracy as hand-rolled horizontal bars
   (copy the pattern from `AdminDashboardPage.tsx`'s readiness-score bar — colored by
   threshold, red-team techniques get a small red-team badge). No new route needed if
   folded into `UserProfilePage.tsx`; if a new page, add route + `AppShell.tsx` nav
   entry (follow existing emoji-icon nav pattern).

**Documentation references:** `backend/app/models/session.py` (`SessionDecision` field
list), `backend/app/models/red_team.py` (`RedTeamMove` field list), existing query
style in `backend/app/api/routes/admin.py` `compliance-analytics` handler (copy its
SQLAlchemy aggregation style, it's the closest existing precedent).

**Verification checklist:**
- `GET /mastery/me` returns non-empty data for a user with at least one completed
  session and one red-team session (test against the currently-stuck session's user,
  `19161d9f-a2ff-4d86-adde-e937789d909b`, who has real move history).
- Debrief `mitre_coverage` for a newly completed session shows `techniques_exercised`
  matching the actual `mitre_technique` values on that session's `SessionDecision` rows
  (verify via `SELECT DISTINCT mitre_technique FROM session_decisions WHERE session_id=...`).
- No new migration required for this phase — confirm no `alembic revision` was run.

**Anti-pattern guards:** do not invent a new `technique_mastery` table yet — this is
query-time aggregation only until it's proven too slow (it won't be, at current data
volumes). Do not touch `RedTeamMove`/`SessionDecision` schemas.

---

## Phase 2 — Red Team Mode: kill the RNG, test tradecraft fit

**Why this order:** it's the single most visible "child's play" tell (confirmed:
`redteam.py` L386 `random.random() < base_success`), and it's contained to one file
plus one migration.

**What to implement:**

1. Migration `00XX_redteam_environment.py` (chain from current head): add
   `environment_state: Mapped[dict]` (JSONB, default `dict`) to `RedTeamSession` —
   stores discovered environment facts (e.g., `{"edr_vendor": "CrowdStrike", "unpatched_cves": ["CVE-2021-34527"], "protected_users_enabled": false}`).
   Follow the `add_column` idiom from `0016_mfa_saml.py` exactly.
2. In `backend/app/api/routes/redteam.py`, extend each `PHASE_MOVES` entry with a
   `requires: dict` describing what environment fact must be true/known for the move
   to be viable (e.g. EternalBlue requires `unpatched_cves` contains
   `"CVE-2017-0144"`), and a `reveals: dict` for Discovery-phase moves describing what
   environment fact a successful Discovery move uncovers.
3. Replace the RNG success calc: for phases other than `discovery`, `succeeded` is
   computed by checking the move's `requires` dict against `session.environment_state`
   — if the player hasn't discovered the fact yet (or the fact doesn't hold), the move
   fails with an *explainable* reason ("You never confirmed this host was unpatched —
   Discovery would have told you"), not a dice roll. Discovery-phase moves keep a
   (smaller, transparent) probabilistic detection-risk element since real recon has
   inherent uncertainty, but success/failure of subsequent moves becomes deterministic
   given what's been discovered.
4. Update `frontend/src/pages/RedTeamPage.tsx` `MoveCard` to show discovered
   environment facts relevant to the current phase (a small "Intel" panel) so the
   player has the information to reason with, not guess blindly.

**Documentation references:** current full `PHASE_MOVES` dict and `execute_move`
handler in `backend/app/api/routes/redteam.py` (already read in full this session —
do not re-fetch, the dict is stable structure to extend, not replace).

**Verification checklist:** a fresh Red Team session where the player skips Discovery
should find later high-impact moves (EternalBlue, LSASS dump) fail with an explanatory
message; a session that plays Discovery first and picks moves matching revealed facts
should succeed deterministically. Confirm via two manual playthroughs (use `/run` or
`/verify` skill against the dev/staging environment, not production).

**Anti-pattern guards:** do not remove `stealth_score`/`impact_score`/`detected`
mechanics — those stay, they're good pressure design. Only the success/fail
*determination* changes from chance to fit-for-environment. Do not break the existing
`RedTeamMove` schema — `succeeded`/`detected`/`stealth_delta`/`impact_delta` columns
are unchanged, only how `succeeded` gets computed changes.

---

## Phase 3 — Real investigation surface (blue-team "pivot on the data" mode)

**What to implement:**

1. Extend scenario seed content (`backend/seed.py`, Colonial Pipeline + SolarWinds
   blocks): add a small set of "hidden" alert-adjacent log lines per scenario — IOCs
   (IPs, hashes, usernames) that don't appear in the main `alert_sequence` but that a
   correct pivot query should surface (e.g., searching the VPN source IP `185.220.101.34`
   surfaces 3 other logins from the same IP across different systems).
2. New WS message type `investigate_query` (client→server) in `handlers.py`/`manager.py`
   (follow the exact existing message-shape convention documented in Phase 0 — `{type,
   ...}` in, `{type, data, server_time}` system-event or a dedicated `investigation_result`
   event out) — takes a free-text or field-based query (start with simple field match:
   IP, hostname, username, process name) against the scenario's hidden IOC set, returns
   matches.
3. Frontend: add a 4th column / collapsible panel to `SimulationRoomPage.tsx` — a query
   input box, results list rendered like existing alert cards (reuse `SEV_BADGE` styling).
   Log which pivots the user tried and whether they found something material
   (`SessionDecision`-adjacent — but this is investigative, not gated, so track it as
   a lightweight new column or JSON field, not a full new table: add
   `investigation_log: Mapped[list]` JSONB to `SimulationSession` via the same
   migration as Phase 2 or a follow-up one).

**Documentation references:** exact WS message catalog and `_stream_alerts` loop in
`backend/app/websocket/handlers.py`/`manager.py` (fully documented in Phase 0 findings
— copy the existing broadcast/event pattern, do not invent a new transport).

**Verification checklist:** a player who pivots on the right IOC surfaces the hidden
log lines; the debrief (Phase 1's real coverage calc) can note investigation activity
in `compliance_evidence` as evidence of active hunting, not just gate-answering.

**Anti-pattern guards:** do not make this gate-blocking (i.e., don't require a pivot to
proceed) — it's an enrichment layer for now, not a hard gate, to avoid breaking the
existing timed-pressure pacing. Do not invent a new full-text search engine — simple
field-equality/substring match over the scenario's own JSON is sufficient at this scale.

---

## Phase 4 — Knowledge checks + spaced repetition

**What to implement:**

1. Migration: new tables `knowledge_checks` (`id, scenario_id nullable, technique_id
   nullable, nist_control_ref nullable, question, options JSONB, correct_index,
   explanation`) and `user_knowledge_check_attempts` (`id, user_id, knowledge_check_id,
   chosen_index, is_correct, created_at`). Follow the `0012_certifications.py`
   table-creation idiom (simple FK + indexed columns, no exotic constraints needed).
2. Author 1-2 knowledge-check questions per existing decision gate for Colonial
   Pipeline and SolarWinds as new seed content in `backend/seed.py` (content-authoring
   task, tie each question to that gate's `nist_control_ref`/`mitre_technique` so it
   feeds the same mastery aggregation from Phase 1).
3. New endpoint `POST /learning/knowledge-check/{id}/attempt`, `GET
   /learning/knowledge-check/next` (returns a question weighted toward the user's
   weakest techniques per `mastery_service.compute_user_mastery`).
4. Frontend: small modal/panel triggered after a gate's consequence reveal in
   `SimulationRoomPage.tsx` ("Why was that the right call?"), and a standalone
   "Daily Drill" entry point (could live on `DailyBreachPage.tsx` or as a new tab)
   surfacing `GET /learning/knowledge-check/next` for spaced repetition on weak areas.

**Documentation references:** `backend/seed.py` gate structure (Phase 0 findings) for
authoring consistency; `backend/app/models/certification.py` as the simplest existing
model to copy the "small lookup + user-attempt join table" pattern from.

**Verification checklist:** a user who answered a gate incorrectly and got the wrong
technique should see that technique's knowledge-check question resurface in "Daily
Drill" within their next few sessions, ranked above techniques they're already strong in.

**Anti-pattern guards:** do not make knowledge checks block gameplay progression in the
main scenario flow — keep them optional/supplementary at first so the core
pressure-driven pacing (BreachReplay's actual differentiator) isn't diluted into a quiz app.

---

## Phase 5 — Certificate integrity (make credentials mean something)

**What to implement:**

1. Add a **mastery-gated criterion** alongside existing threshold checks in
   `cert_service.py`: e.g. `ir_fundamentals` additionally requires
   `compute_user_mastery` showing ≥70% accuracy across all techniques touched by the
   completed scenarios (not just raw session count). Implement as a new check function
   called from `check_and_award_certs`, additive to existing SQL checks — do not
   remove existing criteria, tighten them.
2. **Grandfather clause (mandatory):** any certification already in the `certifications`
   table keeps its `verify_token` valid and displayed as-is — new criteria only affect
   certs not yet issued. Do not write a migration that touches existing rows.
3. Add one **capstone assessment** per cert tier above bronze: a scenario variant
   flagged `is_capstone: true` (new boolean column on `Scenario`, small migration) that
   (a) only counts toward a cert on a first attempt (check `SimulationSession` count for
   that scenario+user before this session), and (b) requires the mastery threshold from
   step 1. This directly addresses the "replay until you get lucky" farming gap without
   building a whole proctoring system.
4. Frontend: `CertificatePage.tsx` — display the mastery percentage that backed the
   cert (pull from the same `compute_user_mastery` call), so the certificate PDF/page
   can honestly say "82% technique mastery across N scenarios" instead of just "completed."

**Documentation references:** full current `CERTIFICATIONS` dict and
`check_and_award_certs` in `cert_service.py` (already read in full this session).

**Verification checklist:** existing certs in the `certifications` table are
byte-identical before/after this phase (run `SELECT * FROM certifications` before and
after deploying, diff the rows). A test user who replays the same scenario 5 times
without improving technique mastery should NOT get a cert from repeated attempts alone.

**Anti-pattern guards:** never write an UPDATE/DELETE against the `certifications`
table as part of this phase. This is additive-criteria-only.

---

## Phase 6 — Instructor / cohort tooling (the enterprise wedge)

**What to implement:**

1. Migration: new `content_assignments` table (`id, organization_id, assigned_by_user_id,
   team_id nullable, user_id nullable, scenario_id nullable, target_technique_id
   nullable, due_date nullable, created_at`) — either a `team_id` or `user_id` target,
   either a `scenario_id` or `target_technique_id` payload (assign a specific scenario,
   or "anything that exercises T1003"). Follow `0013_teams.py`'s table+FK+index idiom.
2. New endpoints in `backend/app/api/routes/admin.py` (extend, don't fork the file):
   `POST /admin/assignments`, `GET /admin/assignments` (org-scoped, reuse
   `require_admin` + manual `organization_id` filter — matches every existing handler
   in this file, do not invent a new permission dependency yet).
3. Extend `/admin/compliance-analytics` response with a `team_skill_gaps` section:
   per-`Team`, aggregate member mastery (reuse Phase 1's `mastery_service` per member,
   averaged) mapped against NIST CSF categories, surfaced as "Team X is weak on
   Detect (DE.CM): 3 of 5 members below 50% mastery."
4. Frontend: extend `TeamsPage.tsx` (captain/admin view) with an "Assign Training" action
   per team, and extend `AdminDashboardPage.tsx`'s existing "compliance" tab with the
   new skill-gap section (it already has the readiness-score/coverage layout to extend,
   per Phase 0 findings — do not build a new dashboard page).

**Documentation references:** full `admin.py` endpoint list and `Team`/`TeamMember`
models (Phase 0 findings) — this phase extends existing plumbing, it does not
introduce a parallel cohort system.

**Verification checklist:** an org admin can assign a scenario to a team; that team's
members see it as a recommended/pinned item; `/admin/compliance-analytics` shows the
new skill-gap section without breaking any existing field in that response (additive
keys only — existing dashboard consumers must not need changes to keep working).

**Anti-pattern guards:** do not add a new user role to the `user_role` Postgres enum
for this — enum alteration is the highest-friction migration pattern in this codebase
(see `001_fix_user_role_enum.py`'s full-table-rewrite approach) and isn't needed yet;
`require_admin` + org scoping is sufficient for v1 instructor permissions.

---

## Phase 7 — Frontend cohesion pass

**What to implement:** wire any new pages into `App.tsx` routes + `AppShell.tsx` nav
(match existing emoji-icon + `NavLink` pattern); actually define `animate-bounce-in`
in `tailwind.config.js` `theme.extend.keyframes/animation` while touching `XPToast.tsx`
for mastery-unlock toasts; audit new components for `breach-*` token usage vs raw
Tailwind classes and pick one convention going forward (recommend: `breach-*` for
backgrounds/borders since it's the more distinctive brand signal, raw Tailwind for
one-off severity colors) — document the decision in a code comment at the top of the
new mastery dashboard component, not a new docs file.

**Verification checklist:** every new page reachable from the nav; no console errors;
`npm run build` succeeds (existing `infra/deploy.ps1` build step is the ground truth
check).

---

## Final Phase — Verification

1. Run `alembic upgrade head` locally against a copy of the schema (not production)
   for every new migration introduced across Phases 2/4/5/6, confirm clean upgrade
   AND downgrade.
2. Grep for anti-patterns: `grep -rn "random.random" backend/app/api/routes/redteam.py`
   should return nothing in the success-determination path after Phase 2 (detection
   risk in Discovery phase is the one intentional exception — confirm it's scoped
   there only).
3. Confirm no phase touched `certifications` table rows destructively (Phase 5 guard).
4. Full manual playthrough: one Red Team session (verify skill-based outcomes), one
   blue-team session with investigation pivots and a knowledge check, check
   `/mastery/me`, check an admin's compliance dashboard shows the new skill-gap section.
5. Deploy via existing `infra/deploy.ps1` only after explicit user confirmation — this
   touches production data (certifications, sessions) and should not go out silently.
