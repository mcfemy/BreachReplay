# Live Arena Mode: a real simulated org, not a translator

Phased plan for the next major initiative after the learning-platform overhaul
(docs/plans/formidable-learning-platform.md, 7 phases, shipped). Not started —
queued for execution via `/do` in a future session. Each phase is self-contained
enough to execute in a fresh chat context. Supersedes the original v1 of this
document (kept in git history) — the core coupling mechanism changed from a
hand-authored move→alert translation table to a genuine simulated
organization both sides interact with. Rationale for the change is below;
read it before touching Phase B/C, the two phases most affected.

## The idea (v2)

v1 of this plan coupled Red Team Mode and the blue-team incident room via a
hand-authored "move → alert" mapping table: attacker executes a scripted
move, a lookup table converts it into a defender-facing alert. That works,
but it's still authored content underneath — every attacker action maps to
one fixed alert, every match on a given scenario eventually looks the same.

The stronger version, inspired by how Antithesis's deterministic simulation
platform works (see research notes below): stop authoring the coupling.
Build a small, deterministic, seeded **simulated organization** —
`OrgState` — that both attacker and defender read and mutate directly.
Alerts, detections, and which moves even succeed are **computed** from that
shared state, not looked up in a table. Same seed always reproduces the same
org and the same incident; different seeds mean effectively infinite
non-repeating content instead of a handful of hand-authored scenarios,
while every match stays fully reproducible (provable fairness for
leaderboards/certification, exactly Antithesis's "perfect reproducibility"
property applied to a training product instead of a bug-finder).

This also happens to make the branching "what if I'd chosen differently"
debrief feature (the original, more modest idea from this conversation)
almost free: if a match is `(seed, ordered action log) → deterministic
OrgState`, replaying the log up to any checkpoint and diverging with a
different action is just... calling the same pure function with a shorter
log plus one different entry. No pre-authored alternate branches needed.

**Explicit scope discipline (read this before Phase B):** Antithesis
simulates actual hardware/network stacks via a custom hypervisor — that is
NOT the right level of fidelity here and would turn this into an
infeasible, multi-year systems project. `OrgState` is a lightweight
discrete-event **object graph** (hosts, credentials, network segments,
detection rules as plain Python objects/JSONB, not virtualized anything).
Keep the entity model small in v1 (see Phase B's explicit field lists) and
resist adding entity types until the core loop is proven fun.

**What does NOT change:** the authored, CISA/SEC-cited real-incident
scenarios (Colonial Pipeline, SolarWinds, etc.) stay the flagship,
trust-building content for the CISO-buyer pitch — "based on a real breach"
is a real credibility signal a synthetic simulation would dilute if it
replaced them. Arena mode is a new, parallel "Infinite Mode" for
replayability/competition, not a replacement for the authored library. The
scenario-ingestion pipeline (weekly CISA/SEC/RSS ingestion, now reliably
scheduled via RedBeat as of this session) keeps growing that separate,
authored moat independently of everything below.

## Known facts from the existing codebase (verified across the prior
## two sessions' work — re-verify anything schema-related before writing
## migrations, since more phases may have landed since this was written)

- `RedTeamSession`/`RedTeamMove` (`backend/app/models/red_team.py`,
  `backend/app/api/routes/redteam.py`): `environment_state` (JSONB) already
  exists as a flat fact-bag (`{"unpatched_smb": true}`) with a `requires`/
  `reveals` dict per `PHASE_MOVES` entry, added in the prior overhaul's
  Phase 2. This is the direct precursor to `OrgState` below — Phase B
  generalizes this flat fact-bag into a real object graph. Do not delete
  the existing flat mechanism; solo Red Team Mode keeps using it unchanged
  (see "what stays separate" in Phase A).
- `SimulationSession`/`SessionDecision` (`backend/app/models/session.py`):
  alerts/decision gates currently come from `Scenario.alert_sequence`/
  `decision_tree` — static, authored, timestamp-driven playback via
  `_stream_alerts` in `backend/app/websocket/handlers.py`.
- WS transport (`handlers.py` + `manager.py`) already supports `alert`,
  `decision_gate`, `decision_result`, `pressure_injection`,
  `investigation_result`, `send_personal` vs `broadcast`. Reusable as-is —
  arena mode needs the SAME event shapes fed by a different source
  (the simulation engine instead of static JSON), not a new transport or
  new frontend rendering code.
- `mastery_service.compute_user_mastery` aggregates by `technique_id`/
  `mitre_technique` already — an arena match just needs to keep writing
  `RedTeamMove`/`SessionDecision`-shaped rows (or equivalent) with those
  fields populated; zero changes needed to the mastery engine itself.
- Ingestion pipeline (`backend/app/pipeline/celery_app.py`,
  `backend/app/pipeline/tasks.py`) now uses RedBeat (Redis-backed schedule
  state, fixed this session) — unrelated to arena mode but keep in mind
  this is the OTHER moat-building mechanism running in parallel; don't
  let arena-mode work crowd out monitoring that pipeline's actual output.

## Architecture: the Org Simulation Engine

### Core entities (v1 scope — resist adding more)

- `Host`: `id, hostname, role (workstation|domain_controller|server|scada),
  network_segment_id, unpatched_cves (list[str]), edr_installed (bool),
  compromise_level (none|foothold|admin|domain_admin), isolated (bool —
  defender action sets this)`.
- `NetworkSegment`: `id, name, monitored (bool — SIEM coverage), reachable_from
  (list[segment_id] — coarse firewall model, no real packet simulation)`.
- `Credential`: `id, username, privilege (user|admin|domain_admin),
  valid_on_host_ids (list[str]), harvested (bool), disabled (bool —
  defender action sets this)`.
- `DetectionRule`: `id, technique_id, requires (host/segment conditions,
  e.g. edr_installed AND segment.monitored), base_detection_probability`.
- `OrgState` (the aggregate, JSONB-serializable): `hosts, segments,
  credentials, detection_rules, global_flags (dict — e.g.
  "backups_immutable": bool, affects ransomware-phase outcomes)`.

### Generation and determinism

`generate_org_state(seed: int, archetype: dict) -> OrgState` — a pure,
deterministic function (Python's `random.Random(seed)`, never the global
`random` module) that builds a small org (v1: ~8-15 hosts, 2-3 segments) from
an archetype (industry vertical, size, security maturity — reuse the
existing `Scenario.industry_vertical`/`difficulty` vocabulary for
consistency). Same seed → byte-identical `OrgState` every time.

### The action log (event sourcing, not state snapshots)

An `ArenaMatch` stores `seed` + an ordered list of actions (attacker moves
AND defender responses, interleaved by timestamp) — NOT repeated `OrgState`
snapshots. `replay(seed, archetype, actions[]) -> (OrgState, Event[])` is a
pure function: given the same inputs it always produces the same final state
and the same emitted events (alerts, detections, decision gates) in the same
order. This is what makes rewind/branching (Phase G) nearly free once this
exists, and it's structurally identical to `RedTeamMove`/`SessionDecision`
tables that already exist — an arena match's action log is just those same
row shapes, ordered, against a generated org instead of a scripted one.

### How moves/detections work against real state (replaces flat `requires`)

An attacker action's success is evaluated against the actual `OrgState`
object graph instead of a flat boolean dict — e.g. "Pass the Hash" succeeds
if the attacker holds a harvested, non-disabled `Credential` valid on the
target `Host`, checked as a real object relationship. Detection is computed
per-action against relevant `DetectionRule`s covering the affected host's
segment (EDR + monitored segment = high detection chance; unmonitored
segment = attacker can strategize around it) instead of a fixed
`detection_risk` float per move — this is strictly more expressive than
today's `PHASE_MOVES` catalog and subsumes it (the existing catalog's
`tactic/technique_id/tool/description` fields stay as flavor text per
action type; only the success/detection math changes).

## Phase A — Data model

**What to implement:**
1. New models (new migration, verify actual current head via grep first —
   do not assume): `ArenaOrgArchetype` (small config table, or just a Python
   dict constant if the flexibility isn't needed yet — decide based on
   whether non-engineers need to author archetypes; default to a Python
   constant for v1, add a table only if that proves too rigid) and
   `ArenaMatch`: `id, seed (int), archetype_key, mode (enum: pvp |
   human_defends_vs_ai | human_attacks_vs_ai), attacker_user_id (nullable),
   defender_user_id/team_id (nullable), status (lobby|active|attacker_won|
   defender_won|abandoned), started_at, completed_at, final_org_state_cache
   (JSONB, nullable — a cached replay result for fast debrief loading, NOT
   the source of truth; the action log is the source of truth)`.
2. New model `ArenaAction`: `id, match_id (FK), sequence_number, actor (
   attacker|defender), action_type, payload (JSONB), created_at`. This is
   the event-sourced action log. Index on `(match_id, sequence_number)`.
3. Additive only — do not touch `RedTeamSession`/`SimulationSession`/
   `RedTeamMove`/`SessionDecision` schemas. Solo Red Team Mode and solo/
   multiplayer blue-team scenarios keep working exactly as they do today,
   completely unaffected — this is a new parallel system.

**Verification:** migration dry-run, models compile, no existing table
touched, confirm `ArenaAction` ordering is enforced (unique constraint on
`(match_id, sequence_number)`).

## Phase B — Simulation engine core (was: move→alert translator)

**What to implement:** `backend/app/services/org_simulation.py`:
- `generate_org_state(seed, archetype) -> OrgState` as specified above.
- `apply_attacker_action(state, action) -> (new_state, detected: bool,
  alert: dict | None)` — pure function, no DB access, no randomness outside
  a `random.Random(seed_derived_from(match_id, sequence_number))` local
  instance (never touch the global `random` module — determinism depends
  on this).
- `apply_defender_action(state, action) -> new_state` — e.g. isolate host
  (sets `Host.isolated=True`, removes it from attacker-reachable graph),
  disable credential, patch a service.
- `replay(seed, archetype, actions[]) -> (final_state, all_events[])` —
  folds the action log through the two functions above in order. This is
  the ONLY function that should ever be called to reconstruct match state;
  never trust a cached snapshot without being able to regenerate it from
  this.
- Alert generation reuses the EXISTING alert shape (`timestamp, severity,
  source_system, rule_id, description, raw_log`) so it flows through the
  same `build_alert_event` WS helper already used for scripted scenarios —
  no frontend change needed to render it.

**Verification:** property-style test (this is a good place to actually use
the property-based-testing philosophy Antithesis/Hegel are built on, even
without adopting their tools) — for N random seeds, confirm `replay` is
deterministic (same seed + actions → byte-identical output across repeated
calls) and confirm no action sequence can crash the function (fuzz random
action orderings against a few generated orgs).

## Phase C — Live match orchestration (was: dynamic decision gates)

**What to implement:**
1. Extend `backend/app/websocket/handlers.py` with an arena-match-scoped
   session: attacker moves call `apply_attacker_action`, immediately
   broadcast the resulting alert (if any) to the defender via the existing
   `alert` event; certain outcomes (state transitions like
   `compromise_level` reaching `domain_admin`, or a `DetectionRule` firing
   at high confidence) generate a decision gate for the defender using a
   small library of response templates (contain/isolate/monitor/escalate)
   parameterized by the actual affected `Host`/`Credential`, not
   pre-authored JSON.
2. Defender responses call `apply_defender_action`, which mutates the SAME
   `OrgState` the attacker is querying — this is the real bidirectional
   coupling: isolating a host actually removes it from what the attacker's
   next lateral-movement action can reach, computed, not scripted.

**Verification:** two-browser-tab playtest — confirm a defender's
containment action measurably and correctly changes what the attacker can
subsequently do (e.g. isolated host is unreachable for lateral movement),
and confirm the action log alone can reconstruct the exact same outcome via
`replay()`.

## Phase D — AI attacker policy bot

**What to implement:** deterministic, rule-based policy (NOT an LLM call
per move — see anti-pattern guards) operating against real `OrgState`:
discovery-equivalent actions first, then pick the highest-value reachable
action given current state, difficulty-tunable (harder bot evaluates more
of the state graph before acting, easier bot acts more greedily/noisily).
Because the environment itself is now rich, a fairly simple policy produces
varied-feeling play for free — most of the complexity lives in
`OrgState`, not the bot.

**Verification:** AI-attacker matches complete end-to-end unattended;
difficulty settings measurably change pacing/outcomes across repeated seeds.

## Phase E — AI defender policy bot

**What to implement:** mirror of Phase D on the defense side — reacts to
generated alerts/decision gates via `apply_defender_action`, accuracy/speed
tunable by difficulty. Replaces today's purely narrative
`_blue_team_response` flavor text in solo Red Team Mode's blue-team-vs-AI
path IF that's wanted later — v1 scope is just the new arena AI-defender
mode, do not touch solo Red Team Mode's existing narrator in this phase.

**Verification:** AI-defender matches complete end-to-end unattended;
difficulty settings measurably change outcomes.

## Phase F — Matchmaking, lobby, and spectator UI

**What to implement:** new frontend page `ArenaLobbyPage.tsx` — mode/
difficulty selection, PvP queue/invite (reuse patterns from
`SessionMultiplayerLobbyPage.tsx`), and a live view during a match
combining Red Team Mode's move list/Intel panel with the blue-team alert
feed/decision gates side by side. Spectator mode (read-only WS subscription)
as a stretch goal, not a v1 blocker.

## Phase G — Multiverse replay / branching debrief

**What to implement:** now that matches are event-sourced, add a debrief
view that renders the action log as an explorable tree — click any past
action, see `replay(seed, archetype, actions[:i] + [alternate_action])`
computed live, showing what would have happened with a different choice at
that point. This is the Antithesis-inspired "multiverse map" feature,
except genuinely computed rather than a UI skin over pre-authored branches
— it falls out of Phase B's architecture almost for free. Reuse
`SessionReplayScrubber.tsx`'s existing scrubber pattern as the base, extend
it to support branching instead of pure linear playback.

**Verification:** for a completed match, selecting an alternate action at
any past point produces a different-but-consistent alternate outcome via
`replay()`, without mutating the original match's action log.

## Phase H — Balance, pacing, symmetric win conditions

Explicit defender-side win condition (contain before impact threshold, or
survive a time limit with detection kept low) so both sides have a legible
stake — today only the attacker side has clean win/loss states. Tune
action/alert pacing for ~15-25 minute matches.

## Phase I — "Addictive" layer (do last, only after A-H are solid)

Rank/ELO per player, arena leaderboard, matchmaking queue with estimated
wait, post-match rank-change animation (extend `XPToast.tsx` conventions).
Pure engagement polish — a mechanically sound but unranked arena is still
useful; a ranked-but-broken one is not.

## Anti-pattern guards (apply across every phase)

- Do not simulate actual hardware/network packets/VMs — `OrgState` is a
  lightweight object graph, not a hypervisor. If a phase's implementation
  starts requiring anything resembling real network emulation, that's a
  sign of scope creep — stop and simplify the entity model instead.
- Do not call an LLM per attacker/defender bot decision — deterministic
  rule-based policies only, for fairness-tuning and speed. LLM use, if
  wanted later, belongs in post-match narrative color (e.g. a generated
  "war story" summary of a match), never in the live decision loop.
- Do not use the global `random` module anywhere in `org_simulation.py` —
  always a `random.Random(seed)` instance, or determinism (and therefore
  Phase G's branching replay) silently breaks.
- Do not let this replace or reduce investment in the authored real-incident
  scenario library — it's a new parallel mode, and the two moats
  (authored-content pipeline + private-scenario lock-in) described in the
  product blueprint still matter independently of this.
- Do not start Phase I before A-H are solid.

## Final Phase — Verification

Full manual playthrough of all three modes end to end; confirm
`mastery_service.compute_user_mastery` picks up arena-match technique data
with zero changes to that function; confirm solo Red Team Mode and solo/
multiplayer blue-team scenarios are completely unaffected; confirm Phase G's
branching replay produces consistent, non-mutating alternate outcomes for a
sample of completed matches.
