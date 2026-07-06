# BreachReplay

BreachReplay is a cybersecurity incident-response training platform that converts real-world
breach disclosures and threat advisories (CISA, SEC filings, public post-mortems) into
interactive, multi-tenant SOC tabletop simulations — plus a live, real-time attacker-vs-defender
"Arena" mode with no equivalent among existing IR training tools.

Live at [breachreplay.com](https://breachreplay.com).

---

## What it does

**Scenario-based tabletop training**
- A weekly ingestion pipeline pulls real breach disclosures (CISA advisories, SEC filings, RSS
  feeds) and an AI pipeline (Claude) extracts them into playable scenarios, tagged against MITRE
  ATT&CK techniques and reviewed via an admin draft/approval workflow.
- Solo or multiplayer (role-based commander seats, live presence, voting lobbies) incident-response
  sessions with branching decision gates and a live SIEM-style alert feed.
- Post-simulation debrief: AI-generated performance report, NIST SP 800-61 / MITRE ATT&CK coverage
  mapping, decision audit log, and a shareable completion certificate.

**Live Arena Mode** — real-time PvP and AI-driven Red vs Blue
- Human vs human, human vs AI-attacker, or human vs AI-defender matches on a shared, seeded,
  deterministic simulated organization (hosts, credentials, network segments) — same seed always
  reproduces the same incident, different seeds give effectively unlimited scenarios.
- ELO-based ranking and leaderboard, matchmaking queue, and a multiverse branching-replay debrief
  (rewind to any past action and see what a different choice would have produced).
- Scheduled synchronized Live Events with public countdown/leaderboard pages, anonymous spectator
  mode for in-progress matches, and shareable public replay links with aggregate "you beat X% of…"
  stats (Global Incident Response Index).

**Spaced-repetition learning**
- A supplementary "Daily Drill" of knowledge checks, weighted toward each user's weakest MITRE
  techniques via a mastery-tracking service — separate from the main decision-gate flow.

**Enterprise integrations**
- SAML 2.0 SSO (SP-initiated, custom implementation) for corporate identity federation.
- SIEM webhook streaming (Splunk HTTP Event Collector, Microsoft Sentinel) so simulation alerts can
  flow into a customer's real security tooling.
- A Slack slash command for pulling scenario snippets directly into a workspace.
- Stripe-based billing for Enterprise subscriptions.

---

## Technology stack

- **Backend**: FastAPI, SQLAlchemy (async), PostgreSQL with pgvector, Celery + Redis for scheduled
  and background work (weekly ingestion, Live Arena event scheduling, matchmaking sweeps).
- **Real-time**: WebSockets for multiplayer presence, live Arena match orchestration, and spectator
  broadcasts.
- **AI**: Anthropic Claude API for scenario extraction from source documents and AI-assisted
  debrief grading.
- **Frontend**: React, Vite, TypeScript, Zustand, TailwindCSS.
- **Infra**: AWS (EC2, S3), Docker Compose, nginx, Let's Encrypt TLS, hardened security headers,
  scale-to-zero cost control via a CloudWatch-triggered Lambda.

See [breachreplay.com/security](https://breachreplay.com/security) for the current security and
data-handling posture.

---

## Status

Core tabletop simulation, ingestion pipeline, and compliance debrief reporting are live in
production, alongside a fully shipped Live Arena Mode (data model through ranking/spectator
polish) and the Live Breach Events initiative (shareable replays, live ticker, public stats,
scheduled events, spectator mode). SAML SSO, SIEM streaming, and Slack integration are implemented
for Enterprise accounts. A formal third-party security audit (e.g. SOC 2 Type II) has not yet been
completed — see the security page for specifics.

---

## Roadmap

- Multi-branching decision trees for the core tabletop flow (beyond Arena's existing branching
  replay).
- Threat-hunting sandbox (interactive terminal / mock packet viewer for IOC discovery).
- Immutable, WORM-stored compliance evidence exports for audit packages.
- IR-policy RAG: grade tabletop performance against a customer's own playbooks, not just generic
  frameworks.
