# BreachReplay — close Phase 1, start Phase 2 (action console core loop)

Single command. Do Part A, then Part B, then follow Part C for all of Phase 2.

**Source of truth is Section 4 "Phase 2 — Action console core loop" of
`docs/BREACHREPLAY_GAME_OVERHAUL_SPEC.md` in this project.** This prompt
reproduces that section's binding detail so there is no ambiguity. Build exactly
what the spec says — the verbs, costs, engine module name, table, and WebSocket
message types below are the spec's, not suggestions. Do not substitute your own
verb set or clock model.

---

## Part A — close Phase 1

The `/teaser/answer` idempotency fix is signed off (commit `709d157` on
`phase-1-teaser`; verified: fix present in remote, teaser suite 11 passed, full
suite 359 passed, zero regressions).

1. Merge PR #1 into `main`. Use `gh pr merge 1 --squash --delete-branch` if the
   GitHub CLI is authenticated; otherwise fast-forward `main` to
   `phase-1-teaser`, push, and delete the remote `phase-1-teaser` branch.
2. Confirm `main` contains `709d157`'s changes and that `cd backend && pytest`
   is green on `main` before starting Part B. State the test count.
3. Do NOT implement the deferred Postgres partial-unique-index hardening.

---

## Part B — Phase 2: action console core loop

Cut branch `phase-2-action-console` off the updated `main`.

**Goal:** replace multiple-choice decision gates with verbs against hidden state
on an attacker clock. This is the transformation from quiz to game.

### The loop (player's view)

- **Left — alert feed:** the existing `alert_sequence`, now streamed on the
  attacker clock instead of gated.
- **Center — network map:** the Phase 1 `frontend/src/components/NetworkMap.tsx`
  component (states `clean | pulsing | compromised | contained`), but the player
  only sees what they have *earned* — unexamined hosts render dim/unknown
  (fog-of-war).
- **Right — action console:** 8 verbs, each with a **time cost** that advances
  the attacker clock:

| Verb | Cost | Returns |
|---|---|---|
| `query logs <host>` | 30s | Evidence lines drawn from `hidden_iocs` for that host |
| `scan network` | 45s | Reveals node states/edges (fog-of-war lift) |
| `isolate <host>` | 20s | Cuts that host's edges; stops lateral movement through it |
| `image disk <host>` | 90s | Deep evidence: persistence mechanisms, dropped files |
| `interview user <host>` | 60s | Human-layer clue (phishing origin, shared creds) |
| `block ip <addr>` | 15s | Kills C2 for that address if correct |
| `reset creds <account>` | 40s | Stops credential-reuse lateral movement |
| `escalate` | 0s | One-time: freezes attacker clock 60s ("management call"), score penalty |

- **Attacker clock:** the breach advances through its real stages (compiled from
  `decision_tree` + `pressure_injections` into a stage timeline) whether or not
  the player acts. Every verb spends time. Tension = choosing what to look at,
  exactly like real IR.
- **Win/loss:** contain the attack path before the final-stage event
  (exfil/encryption) fires. Partial containment scores partially.
- **Scoring:** containment speed + evidence found (`hidden_iocs` discovered) +
  precision (wrong isolations penalized — isolating `WEB-02` while the attacker
  is on `FIN-03` has a cost, like real life). Feed the final score into
  `xp_service.award_xp` with `source_type="action_run"`.
- **Debrief:** existing AI debrief pipeline, plus the comparison this product
  uniquely owns: *"Your containment: 6m 40s. The real team at Colonial: 6 days.
  Here's what they did on day 1 vs what you did in minute 1."* Pull the real
  timeline from the scenario's source fields.

### Build items

**Backend**

- New engine module `backend/app/services/action_engine.py`:
  - Compiles a scenario (`alert_sequence`, `decision_tree`,
    `pressure_injections`, `hidden_iocs`) into a **deterministic stage timeline
    + hidden world state** (hosts, edges, IOC placement). Reuse the Arena
    seeded-org generator (`arena_*` services) for world synthesis where the
    scenario lacks explicit topology — same seed, same run, which Phase 4
    depends on.
  - Pure server-authoritative: client sends verbs, server returns revealed
    state deltas. Never ship `hidden_iocs` or the full timeline to the client.
- Extend the existing WebSocket simulation engine (the server counterpart of the
  `useSimulationSocket` hook) with message types `action.submit`, `state.delta`,
  `clock.tick`, `stage.advance`, `run.end`. Keep the old decision-gate message
  types working — org tabletop mode still uses them.
- New table `action_runs` (Alembic migration): run id, user id, scenario id,
  seed, mode (`daily | scenario | teaser`), action log (JSONB, timestamped
  verbs), score breakdown, duration. The action log is the replay format for
  Phase 4 ghosts and the existing `SessionReplayScrubber`.
- Daily Breach backend: switch daily challenge generation (`daily_challenge`
  model) to produce an action-mode run (same scenario + seed for all players
  that day), 8-minute cap enforced server-side.

**Frontend**

- `ActionConsole.tsx`: the 8 verbs as tappable chips with cost labels; targets
  picked by clicking the map (mobile-first — typing is desktop sugar via a
  command input, not the primary path).
- Rework the `DailyBreachPage.tsx` gameplay section to action mode. Keep the
  existing streak/score/leaderboard chrome — it is already good.
- `SimulationRoomPage.tsx`: add "Compressed Run (10 min)" as the default mode
  for individual users; org sessions keep the full tabletop flow untouched.
- Clock UI: the attacker clock is *visible pressure* — a stage progress bar in
  the `bleed` color that creeps, with the next stage label redacted
  (`▮▮▮▮ in 2:10`).

### Acceptance criteria / QA checklist (all must be green to sign off)

- [ ] Same scenario + seed always produces an identical world state and stage
      timeline (determinism test in pytest).
- [ ] All 8 verbs resolve server-side with the exact time costs above; verb time
      advances the attacker clock; `escalate` is one-time and freezes the clock
      60s with a score penalty.
- [ ] Server never ships `hidden_iocs` or the full stage timeline to the client;
      the client learns hidden state only through verb-result deltas
      (anti-leak test, mirroring the Phase 1 teaser leak test).
- [ ] Win and loss are both reachable and correct: containment before the
      final-stage event wins; partial containment scores partially; wrong
      isolations carry a precision penalty.
- [ ] Score feeds `xp_service.award_xp` with `source_type="action_run"`.
- [ ] `action_runs` rows are written with a timestamped verb log usable as a
      replay (Phase 4 / `SessionReplayScrubber` format).
- [ ] Old decision-gate WebSocket message types still work (org tabletop mode
      unbroken) — regression-tested.
- [ ] Daily Breach runs in action mode: same scenario + seed for all players
      that day, 8-minute server-enforced cap.
- [ ] One named scenario (state which — Colonial Pipeline is the natural pick,
      matching the Phase 1 teaser slice) plays end to end: fog-of-war reveal,
      verbs spending clock, attacker advancing, win/lose terminal, debrief with
      the real-vs-player timeline comparison.
- [ ] Frontend typecheck + build clean; `cd backend && pytest` fully green with
      zero regressions against the post-merge baseline (state before/after
      counts).

### Scope boundary (do NOT build in Phase 2)

- No juice pass (typewriter polish, Web Audio cues, shareable run cards, emoji
  grids) — Phase 3.
- No ghost racing / async multiplayer — Phase 4 (but keep the `action_runs`
  verb log in the replay-ready format Phase 4 needs).
- No tone overhaul sweep — Phase 5.

---

## Part C — checkpoint rhythm (all of Phase 2)

Same rhythm as Phase 1, non-negotiable:

- Commit and push after each major item (engine, WS message types, `action_runs`
  migration, ActionConsole UI, Daily Breach switch), not one giant commit.
- After each major item, stop and report: what landed, the exact test command
  run and its output, and what is next. Then wait.
- Do not mark any checklist item done on a claim — every "done" is backed by a
  test run or a verifiable artifact (commit hash, passing suite).
- No phase-complete declaration until every acceptance-criteria box is green.
  Anything deferred is called out explicitly in the commit/PR, never folded in
  silently.
- Open PR #2 for `phase-2-action-console`; do not merge it. It is a review gate,
  reviewed the same way PR #1 was.

Start with Part A. Report back when Phase 1 is merged and `main` is green before
beginning Part B.
