# BreachReplay Game Overhaul — Build Spec

**Audience for this document:** Claude Code, working in the `breachreplay` repo.
**Owner:** Femi (Femylabs LLC). Femi directs, Claude Code builds, external QA review happens at the end of every phase before the next one starts.
**Repo state assumed:** current `main` as of July 2026 (Arena mode, Daily Breach, XP service, seeded org engine all shipped).

---

## 0. Thesis and non-negotiables

### What we are fixing

The platform's metagame is excellent (XP tiers, ELO Arena, streaks, achievements, replays). The core gameplay atom is not: it is a timed multiple-choice quiz (`decision_tree` gates with `correct_index`, 60s countdown). Quizzes read as training. Games read as agency. This overhaul replaces "pick the right answer" with "take actions against a hidden state on a moving attacker clock," and fixes the funnel so a visitor feels the game before being asked to sign up.

### Non-negotiable constraints (apply to every phase)

1. **Session length caps.**
   - Landing teaser: 60–90 seconds, hard cap.
   - Daily Breach: 8 minutes max, target 5–6. Enforce in the engine, not just copy.
   - Full scenarios: add a **10-minute compressed mode** as the default for individual users. The current `estimated_minutes` default of 45 stays available only as "Full Tabletop" for org/enterprise accounts. Use the existing `compression_ratio` field to drive this.
2. **Tone: zero academic language on any player-facing surface.** The audience is security professionals, IT people, students, and curious young minds. Banned words in player-facing UI: *training, curriculum, learning objectives, module, assessment, competency, courseware, tabletop* (keep "tabletop" only inside the enterprise/org area). Replacement register: challenge, run, breach, contain, beat, survive. Educational content stays; it is delivered as consequence and debrief, never as a lesson header.
3. **No video, no heavy assets.** All atmosphere comes from typography, SVG animation, CSS, and Web Audio. Nothing in this spec should meaningfully increase bundle size or server RAM.
4. **Don't break the enterprise surface.** SAML, SIEM streaming, Slack, Stripe, org tabletops keep working. The consumer game and the enterprise product share an engine but diverge in copy and entry points.
5. **Every phase ends shippable.** No phase may leave `main` in a state that can't deploy.

---

## 1. Visual direction (applies from Phase 1 onward)

Ground the aesthetic in one concrete image: **a SOC at 2 a.m. during a live incident.** Not a hacker-movie cliché, not a corporate dashboard.

### Design tokens

Create `frontend/src/theme/tokens.ts` and refactor toward it as pages are touched (don't do a big-bang restyle).

- **Palette (name / hex / role):**
  - `void` `#0B0F14` — page background (blue-black, not pure black)
  - `panel` `#121A23` — cards, consoles
  - `phosphor` `#FFB454` — primary accent: amber CRT phosphor. Buttons, active states, score. Deliberately *not* green-on-black; amber is the color of real ops-room terminals and avoids the generic hacker look.
  - `bleed` `#E5484D` — compromise, spreading infection, attacker clock
  - `contain` `#3DD68C` — contained hosts, correct calls
  - `dim` `#8A97A5` — secondary text, timestamps
- **Type:**
  - Display: **Space Grotesk** (700) — headlines, scores, the dare on the landing page
  - Terminal/data: **IBM Plex Mono** — alert feed, action console, logs, timestamps
  - Body: **Inter** — everything else
- **Signature element:** the **live network topology map** — an SVG of the target org's hosts where compromise visibly bleeds from node to node in `bleed` red, and containment snaps nodes to `contain` green. This one element appears on the landing teaser, in Daily Breach, in scenarios, and on share cards. It is the brand.
- **Motion rules:** alert feed lines type themselves in (typewriter, ~20ms/char). Node infection pulses before it spreads. One subtle screen shake (2px, 120ms) on a breach-critical event. Respect `prefers-reduced-motion` everywhere. No scroll-triggered marketing animations.
- **Sound (Phase 3):** Web Audio only, three cues max — soft tick on alert arrival, low thud on host compromised, resolved chime on containment. Muted by default with a visible toggle; remember the choice per browser.

---

## 2. Phase plan overview

| Phase | Name | Why this order | Rough size |
|---|---|---|---|
| 1 | No-auth landing teaser | Distribution is the bottleneck, not gameplay depth | S–M |
| 2 | Action console core loop | Replaces the quiz atom; biggest gameplay change | L |
| 3 | Juice pass + share cards | Makes 1 and 2 feel alive; creates the viral artifact | M |
| 4 | Ghost racing (async multiplayer) | Multiplayer feel without concurrent-player cold start | M |
| 5 | Tone/copy overhaul + session-length enforcement + cleanup | Locks in the identity | S–M |

Phases 1 and 2 are independent enough to build in either order, but ship 1 first: it starts converting traffic while 2 is being built.

---

## 3. Phase 1 — No-auth landing teaser

**Goal:** a first-time visitor is *playing* within 5 seconds of page load and hits signup only after their first win/loss.

### Player experience

1. Visitor lands on `breachreplay.com`. Above the fold, no marketing hero. Instead:
   - The network map of a small fictional org (6–8 nodes: `MAIL-01`, `WEB-02`, `DC-01`, `FIN-03`, etc.), one node already pulsing red.
   - The alert feed starts typing immediately: real-derived alerts from one flagship scenario (Colonial Pipeline is the natural pick given the source PDF already in the repo).
   - A 60-second countdown in `phosphor`.
   - Headline (Space Grotesk): **"This breach really happened. It took them 6 days to contain it. You have 60 seconds."**
2. Player gets **one decision** — teaser uses the existing decision-gate mechanic (this is the one place the quiz atom survives, because a single high-stakes choice is fine): e.g., *"Lateral movement detected from MAIL-01. Isolate which host?"* with 3 clickable nodes on the map itself (the map is the input, not a button list).
3. Immediate consequence: correct → infection halts, node snaps green, score flourish. Wrong → red bleeds across two more nodes, "FIN-03 encrypted."
4. End card either way: *"That was step 1 of 7 in the real Colonial Pipeline attack. The real team missed it. Play the full breach free."* → single-field signup (email + password, or the existing OAuth callback flow).

### Build items

- New route `/` replaces or wraps `LandingPage.tsx`. Keep the existing marketing content below the fold (pricing, security, enterprise links must remain reachable — enterprise buyers still land here).
- **Anonymous session endpoint:** `POST /api/teaser/start` returns a signed anonymous token + the teaser scenario payload (static JSON derived from one approved scenario; do NOT open the full scenario API unauthenticated). `POST /api/teaser/answer` records the outcome keyed to the anon token. Rate-limit by IP via the existing slowapi setup.
- **Conversion continuity:** if the visitor signs up within the same browser session, attach the teaser result to the new account (first achievement pre-earned — wire to `xp_service` `first_blood` or a new `teaser_survivor` achievement). This "you already have progress" moment measurably lifts signup completion.
- Network map component: `frontend/src/components/NetworkMap.tsx` — pure SVG, props: nodes, edges, per-node state (`clean | pulsing | compromised | contained`), click handler. Built to be reused in Phases 2–4 and in share cards.
- Analytics events (whatever lightweight mechanism exists or a simple backend counter table): `teaser_started`, `teaser_decided`, `teaser_completed`, `signup_from_teaser`. Femi needs the funnel numbers.

### Acceptance criteria / QA checklist

- [ ] Cold visit to `/` on a throttled mobile connection: alert feed visibly typing in under 3s, interactive in under 5s.
- [ ] Entire teaser playable with zero auth, zero cookies-wall, on mobile Safari and Chrome.
- [ ] Wrong answer and right answer both produce a visible map consequence within 300ms.
- [ ] Signup after teaser lands the user in Daily Breach or scenario library with the teaser achievement visible.
- [ ] Enterprise links (pricing, security, SSO login) still reachable and unchanged.
- [ ] slowapi rate limit prevents teaser API abuse (verify with a scripted burst).
- [ ] Lighthouse performance ≥ 85 mobile on `/`.

---

## 4. Phase 2 — Action console core loop

**Goal:** replace multiple-choice decision gates with verbs against hidden state, on an attacker clock. This is the transformation from quiz to game.

### The loop (player's view)

- Left: **alert feed** (existing `alert_sequence`, now streamed on the attacker clock instead of gated).
- Center: **network map** (Phase 1 component) — but the player only sees what they've *earned*: unexamined hosts render dim/unknown.
- Right: **action console** — 8 verbs, each with a **time cost** that advances the attacker clock:

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

- **Attacker clock:** the breach advances through its real stages (from `decision_tree` + `pressure_injections`, recompiled as a stage timeline) whether or not the player acts. Every verb spends time. Tension = choosing what to look at, exactly like real IR.
- **Win/loss:** contain the attack path before the final-stage event (exfil/encryption) fires. Partial containment scores partially.
- **Scoring:** containment speed + evidence found (`hidden_iocs` discovered) + precision (wrong isolations penalized — isolating `WEB-02` while the attacker is on `FIN-03` has a cost, like real life). Feed the final score into `xp_service.award_xp` with `source_type="action_run"`.
- **Debrief:** existing AI debrief pipeline, plus the killer comparison this product uniquely owns: *"Your containment: 6m 40s. The real team at Colonial: 6 days. Here's what they did on day 1 vs what you did in minute 1."* Pull the real timeline from the scenario's source fields.

### Build items

**Backend**
- New engine module `backend/app/services/action_engine.py`:
  - Compiles a scenario (`alert_sequence`, `decision_tree`, `pressure_injections`, `hidden_iocs`) into a deterministic **stage timeline + hidden world state** (hosts, edges, IOC placement). Reuse the Arena seeded-org generator (`arena_*` services) for world synthesis where the scenario lacks explicit topology — same seed, same run, which Phase 4 depends on.
  - Pure server-authoritative: client sends verbs, server returns revealed state deltas. Never ship `hidden_iocs` or the full timeline to the client.
- Extend the existing WebSocket simulation engine (`useSimulationSocket` server counterpart) with message types: `action.submit`, `state.delta`, `clock.tick`, `stage.advance`, `run.end`. Keep the old decision-gate message types working — org tabletop mode still uses them.
- New table `action_runs` (Alembic migration): run id, user id, scenario id, seed, mode (`daily | scenario | teaser`), action log (JSONB, timestamped verbs), score breakdown, duration. The action log is the replay format for Phase 4 ghosts and the existing `SessionReplayScrubber`.
- Daily Breach backend: switch daily challenge generation (`daily_challenge` model) to produce an action-mode run (same scenario + seed for all players that day), 8-minute cap enforced server-side.

**Frontend**
- `ActionConsole.tsx`: the 8 verbs as tappable chips with cost labels; targets picked by clicking the map (mobile-first — typing is desktop sugar via a command input, not the primary path).
- Rework `DailyBreachPage.tsx` gameplay section to action mode. Keep the existing streak/score/leaderboard chrome — it's already good.
- `SimulationRoomPage.tsx`: add "Compressed Run (10 min)" as the default mode for individual users; org sessions keep the full tabletop flow untouched.
- Clock UI: attacker clock is *visible pressure* — a stage progress bar in `bleed` that creeps, with the next stage label redacted (`▮▮▮▮ in 2:10`).

### Acceptance criteria / QA checklist

- [ ] Same scenario + seed always produces identical world state and stage timeline (determinism test in pytest).
- [ ] Client never receives undiscovered IOCs or future stages (verify via WS message inspection).
- [ ] A player who does nothing loses in ≤ 8 minutes (Daily) with a coherent narrative of what happened.
- [ ] A skilled run can win with time to spare; a sloppy run (wrong isolations) can still partially recover. Play 5 seeded runs and confirm outcomes differ meaningfully by strategy, not luck.
- [ ] `escalate` usable exactly once; clock freeze verified.
- [ ] XP, achievements (`speed_demon`, `perfect_analyst`, streaks) all fire from action runs.
- [ ] Old org tabletop sessions (decision-gate mode) unaffected — regression pass on an org session end-to-end.
- [ ] Full loop playable on a phone with one thumb.
- [ ] pytest suite green in CI, including new engine tests.

---

## 5. Phase 3 — Juice pass + share cards

**Goal:** make Phases 1–2 *feel* alive, and give every finisher a reason to bring the next player.

### Build items

- **Feed juice:** typewriter rendering for all alert lines; severity-tinted timestamps; brief `phosphor` flash on new line.
- **Map juice:** infection pulse → spread animation along edges; containment snap with a 150ms green ring; the single permitted screen shake on final-stage fire. All CSS/SVG, `prefers-reduced-motion` honored.
- **Sound:** the three Web Audio cues from the visual-direction section. Muted by default, toggle in the AppShell header, persisted in localStorage.
- **Share card:** on run end, server renders a PNG (existing `pdf_generator.py` stack can host a Pillow/ReportLab-based renderer, or a small satori-style SVG→PNG step): the final network map state as thumbnail, score, time vs. the real-world containment time ("You: 6m 40s · Real team: 6 days"), scenario name, breachreplay.com. One-tap share (Web Share API on mobile, copy-link fallback) plus a Wordle-style text grid for the Daily (emoji nodes: 🟩🟥⬛ per host outcome) for chat apps.
- **Public run page:** `/r/{run_id}` — extend `PublicReplayPage.tsx` to render action runs read-only with the scrubber. This is the landing page behind every share card; it ends with the teaser CTA.

### Acceptance criteria / QA checklist

- [ ] Every animation ≤ 300ms and interruptible; no jank on a mid-range Android (test with 4x CPU throttle).
- [ ] `prefers-reduced-motion` disables typewriter, pulses, shake — content still fully usable.
- [ ] Sound toggle persists; no audio ever plays before user gesture (autoplay policy).
- [ ] Share card renders correctly for win, loss, and partial outcomes; opens to the public run page; page loads with zero auth.
- [ ] Daily emoji grid pastes cleanly into WhatsApp/iMessage/Slack.

### Phase 3(a) — Targeted escalation & notification proportionality (shipped, migration `0038`)

Not part of the juice-pass build items above — added here after the fact because it shipped under the "Phase 3" label with no corresponding entry in this spec, making it untraceable to written scope. Documenting what was actually built, not retrofitting acceptance criteria to match.

**Why:** logged as a Phase 3 follow-up in `docs/PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md` §10, itself grounded in the CMMC evidence-pack bar set by Carter Schoenberg (Lead CMMC Certified Assessor, VP Assessment & Compliance, SoundWay Consulting) during the Phase 2.5 evidence-layer work: *"an escalation path should very much be in play because otherwise people may be notified that shouldn't be."* The old `escalate` verb was untargeted and free — no way to over-notify, so the notification evidence in a CMMC pack was a checkbox, not a real signal. §10 explicitly deferred the fix to Phase 3.

**What shipped:** `scenarios.notification_matrix` (migration `0038_scenario_notification_matrix`) — each scenario's own authored ground truth for which parties a warranted notification decision covers (id/party/warranted/authority/basis/channel/window/rationale/source_reference), reusing the same field shape as `ClientOrg.notification_matrix` (Phase 2.5 item 4) without conflating the two: that one is a client org's generic contact policy, this one is BreachReplay's per-incident "was notifying this party actually warranted" judgment. `escalate` now costs proportionally to whether the chosen party was actually warranted, mirroring how Proportionate Response already applies collateral cost to over-aggressive containment. Authored matrices so far: SolarWinds (item 1/5, migration `0038`, DIB/FedRAMP-adjacent party list) and Log4Shell (item 2/5, migration `0042_log4shell_notification_matrix`, enterprise-customer/SOC 2 party list — deliberately not a DC3/FedRAMP template). Remaining: MGM, Colonial Pipeline, NHS WannaCry — each needs its own regulator-appropriate party list (PCI/FBI, TSA/NERC CIP, ICO/NCSC), not the DIB-contractor set.

### Phase 3(b) — Technique Dossier (shipped, PRs #31/#32)

Also not part of the original juice-pass build items — same gap as 3(a) above: real, shipped Phase 3 work with no written spec entry until now.

**Why:** post-run debrief and cross-run mastery tracking for player retention and skill-building — the same "show the player what they actually learned" instinct behind `mastery_service.compute_user_mastery` (decision-gate/Red Team accuracy), but for the Action Console's own stage-trigger technique tags, which `mastery_service` never covered. Giving a player a running, cross-run record of which real-world attacker techniques they've now handled (tied to the actual incident it's drawn from) is a retention hook: a reason to come back and fill in the rest of the dossier, not just chase XP.

**What shipped:**
- **Write side** (PR #31): `verb_engine.RunState.encountered_technique_ids` tags every stage whose trigger fires in `_advance_stages` with its `mitre_technique`, regardless of containment success. `action_run_store.finalize` persists these as `TechniqueEncounter` rollup rows (`technique_encounters` table, migration `0039_technique_encounters`) — authenticated runs only, since `ActionRun.user_id` is nullable for teaser mode.
- **Read side** (PR #31): `GET /dossier/me` (`dossier_service.compute_user_dossier`) joins a user's `TechniqueEncounter` rows against the static 30-technique `TECHNIQUE_DOSSIER` content (`technique_dossier.py`), shaped after `mastery_service.compute_user_mastery` but backed by a separate table/source — `mastery_service.py`, `/mastery/me`, and Org Tabletop mode are untouched by any of this.
- **Run-end debrief surfacing** (PR #32): `techniques_encountered` added to the `run.end` payload (name/description only) and rendered inline in `RunDebrief` — fires for every run regardless of auth, so even a teaser player sees what they encountered even though nothing persists for them.
- **Standalone dossier page** (PR #32): `/dossier` (`DossierPage.tsx`) — all 30 techniques grouped by tactic, a visible fill counter ("N/30 entries"), full content (description/incident narrative/source reference) for encountered techniques, locked/no-content cards for the rest. Nav entry added to `AppShell`.

---

## 6. Phase 4 — Ghost racing

**Goal:** multiplayer *feeling* without needing concurrent players. Solves the ELO-queue cold start.

### Player experience

On today's Daily Breach (and any scenario with prior runs), the player can race a **ghost**: another player's recorded action log replayed on the identical seed. Split map view — your org on top, the ghost's org below, both clocks live. You watch them isolate the wrong host in real time while you find the right one. Beat their containment time, take their leaderboard slot.

### Build items

- Ghost source: `action_runs.action_log` (Phase 2). No new recording work needed.
- Ghost selection: default = the run just above you on today's leaderboard; also "race a friend" via any public run link (`/r/{run_id}` gets a **Race this run** button).
- Playback engine: client-side deterministic replay of the ghost's deltas (server sends the ghost's revealed-state timeline once at start — ghosts have no hidden info to protect since their run is public).
- Arena integration: ghost wins award a small ELO-adjacent "index" bump on the existing Global Incident Response Index, not full Arena ELO (keep Arena's ladder for live matches).
- Notification hook: when someone beats your run via a race, email (existing `email_service.py`) — *"[user] just contained your Daily breach 40 seconds faster."* This is the retention loop; one email type only, with an unsubscribe.

### Acceptance criteria / QA checklist

- [ ] Ghost replay is frame-accurate against the original run (determinism test).
- [ ] Racing works on mobile (stacked maps, not side-by-side).
- [ ] "Race this run" from a shared link works for a brand-new account end-to-end (share → signup → race).
- [ ] Beat-notification email sends once per beaten run, respects unsubscribe.
- [ ] Daily leaderboard integrity: ghost races on today's seed count; races on old seeds don't pollute today's board.

---

## 7. Phase 5 — Tone overhaul, session enforcement, cleanup

**Goal:** lock in the identity across every surface.

### Build items

- **Copy sweep** across all player-facing pages (`LandingPage`, `ScenarioLibraryPage`, `DailyBreachPage`, debrief pages, emails, achievements, onboarding modal) applying the register rules from §0.2. Concrete examples of the rewrite:
  - "Scenario-based tabletop training" → "Play real breaches"
  - "Complete the simulation to receive your performance assessment" → "Contain it. Then see how the real team did."
  - "Estimated time: 45 minutes" → "10-minute run"
  - Certificates (`CertificatePage`) keep formal language — they're shown to employers; that's the one surface where formal tone is the feature.
- **Session-length enforcement audit:** verify the caps from §0.1 are engine-enforced in teaser, Daily, and compressed runs; add a "one more run?" end-of-run prompt showing tomorrow's Daily countdown (the existing `CountdownClock`) instead of an open-ended menu.
- **Scenario library re-frame:** present scenarios as **case files** with the real-world stakes up front ("$4.4M ransom paid. 45% of East Coast fuel. Your move.") — data already exists in `description`/source fields.
- **Enterprise/consumer split:** `/` and the game surfaces speak game language; `/enterprise` (or the existing pricing/security pages) keeps the compliance vocabulary (tabletop, NIST, SOC 2 roadmap, SAML). Nav shows the right entry point based on org membership.
- Remove or gate any dead/duplicated flows discovered in Phases 1–4 (log them as found; don't refactor speculatively).

### Acceptance criteria / QA checklist

- [ ] Grep for banned words across `frontend/src` player-facing strings returns only enterprise-surface and certificate hits.
- [ ] A new user's first 15 minutes (teaser → signup → Daily → share) never shows a single academic-register string. Walk it end to end.
- [ ] Enterprise flows unchanged: SAML login, org tabletop, SIEM webhook, Stripe checkout smoke-tested.
- [ ] All Phase 1–4 acceptance checklists re-verified on production build.

---

## 8. QA protocol (all phases)

1. Claude Code opens a PR per phase (or per major item within a phase) with the phase checklist in the PR description.
2. Femi pushes to GitHub and deploys to the existing EC2 stack (staging path if configured, otherwise a short production window off-peak).
3. External QA review per phase: fresh clone of the branch, code review against this spec, checklist verification against the deployed URL for everything reachable without auth, and Femi supplies screen recordings for authenticated/WebSocket flows.
4. Regression floor for every phase: pytest suite green in CI, teaser playable, Daily playable, one org tabletop session, Stripe checkout page loads.
5. No phase starts until the previous phase's checklist is fully signed off.

## 9. Explicit non-goals

- No video or 3D. No react-three-fiber, no Lottie files over 50KB total.
- No native mobile app in this overhaul; mobile web must be first-class instead.
- No rewrite of Arena's live PvP — it already works; Phase 4 feeds it players instead.
- No new pricing work; consumer monetization is a separate decision after funnel data from Phase 1 exists.
