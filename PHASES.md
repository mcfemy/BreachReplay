# BreachReplay — Development Phases

**Project**: AI-powered incident response training platform that converts real breach disclosures into interactive SOC team simulations.

**Stack**: FastAPI + SQLAlchemy async + PostgreSQL/pgvector + Redis + Celery + Anthropic Claude API | React + Vite + TypeScript + Zustand + TailwindCSS

---

## Phase 0 — Hardened Backend Foundation ✅
**Commit**: `5d43b6c`

- FastAPI application skeleton with CORS, structured logging (structlog), Sentry integration
- JWT authentication (access tokens, 15-min expiry) with bcrypt password hashing
- RBAC: roles `OWNER`, `ADMIN`, `ANALYST`, `VIEWER` with route-level enforcement
- Organisation isolation — every resource scoped to `organization_id`
- SQLAlchemy async ORM with PostgreSQL + pgvector for embedding storage
- Alembic migration `0001_baseline` — full schema (users, orgs, scenarios, simulation_sessions, session_decisions, breach_documents, audit_logs)
- Claude ingestion pipeline — converts breach disclosure PDFs into structured scenario data
- WebSocket simulation engine — real-time alert feed, decision gates, team coordination
- Celery + Redis task queue for async document processing
- Rate limiting (slowapi), input sanitisation, security headers (Secure, X-Frame-Options, CSP)
- Docker Compose: postgres, redis, backend API, celery worker

---

## Phase 1 — Auth Session Hardening + Test Suite ✅
**Commit**: `7254cbc`

- Opaque UUID refresh tokens stored in Redis (`rt:{uuid}` → user_id, 7-day TTL), rotating on use
- `/auth/refresh` — validates + rotates refresh token, returns new access + refresh token pair
- `/auth/logout` — revokes refresh token from Redis (server-side logout)
- `/auth/forgot-password` — issues single-use password reset token (`pwd_reset:{uuid}`, 15-min TTL); SendGrid email if configured; returns 200 always (no user enumeration)
- `/auth/reset-password` — validates token, updates bcrypt hash, deletes token (single-use)
- `TokenOut` schema updated to include `refresh_token` field
- Performance indexes migration `0002_indexes` — simulation_sessions, session_decisions, scenarios
- Redis module (`app/core/redis.py`) with async connection pool
- Full pytest suite: auth flows, session lifecycle, scenario CRUD — 3 test files, ~40+ test cases
- FakeRedis (`fakeredis.aioredis`) + SQLite (`aiosqlite`) for hermetic test isolation
- GitHub Actions CI — Python 3.12, pinned deps, `pytest -q` on push/PR to main
- `pytest.ini` with `asyncio_mode = auto`

---

## Phase 2 — Frontend MVP Hardening 🔲

- Auth store (`store/auth.ts`): store refresh token alongside access token; implement token rotation on 401
- API client (`lib/api.ts`): intercept 401 responses, call `/auth/refresh`, retry original request; redirect to login on refresh failure
- Logout flow: call `POST /auth/logout` before clearing local state
- `LoginPage.tsx`: receive and store refresh token from login response
- Session debrief page — post-simulation summary (decisions made, timeline, score)
- Protected route refresh-awareness (don't flash login on valid-but-expired access token)
- E2E smoke test (Playwright or Cypress) covering login → scenario select → simulation start

---

## Phase 3 — Document Ingestion + Admin UI 🔲

- Admin dashboard (role: OWNER/ADMIN only) — user management, org settings
- Breach document upload UI — drag-and-drop PDF upload → Celery task queued
- Claude extraction review — show raw vs extracted fields, allow manual correction before approval
- Scenario approval workflow — DRAFT → REVIEW → APPROVED → PUBLISHED states
- Webhook endpoint for ingestion completion events
- Admin audit log viewer — surface the `audit_logs` table

---

## Phase 4 — Multiplayer + Advanced Simulation 🔲

- Team sessions — multiple analysts join a single `simulation_session` via invite link
- Real-time collaborative decision gates — majority vote or role-based authority
- Observer mode — trainers watch live without influencing decisions
- Session replay — scrub through decision timeline after completion
- Facilitator controls — pause/resume/inject custom alerts mid-simulation
- Presence indicators (who is online, who is deciding)

---

## Phase 5 — Debrief, Reporting + Compliance 🔲

- Full debrief view — decision timeline, correct vs actual choices, MITRE ATT&CK mapping
- PDF export of debrief report (ReportLab, already in deps)
- NIST CSF / MITRE ATT&CK coverage dashboard per scenario
- Compliance evidence package export (for auditors)
- Per-analyst performance tracking over time
- Scenario difficulty calibration based on aggregate decision data

---

## Phase 6 — Platform Scale 🔲

- Migrate to managed Postgres (Supabase or RDS) + pgvector extension in cloud
- S3 / GCS for breach document storage (replace local filesystem)
- Multi-tenant admin console — onboard new organisations without code changes
- Usage analytics and billing hooks
- CDN + edge caching for static scenario assets
- Horizontal Celery worker scaling (ECS / Kubernetes)
- SLA monitoring, on-call alerting (PagerDuty / OpsGenie integration)
