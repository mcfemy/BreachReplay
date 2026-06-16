# BreachReplay

BreachReplay is a professional-grade, AI-powered incident response training platform designed to convert real-world cybersecurity breach disclosures and threat advisories into interactive, multi-tenant SOC team tabletop simulations.

---

## 🚀 Technology Stack

* **Backend Engine**: FastAPI, SQLAlchemy Async, Uvicorn, PostgreSQL with pgvector (for future semantic storage)
* **Real-Time Communication**: Event-driven WebSockets with sub-second multiplayer presence tracking and interactive voting lobbies
* **Asynchronous Task Queue**: Celery, Redis connection pools, pypdf document parsing
* **Artificial Intelligence**: Anthropic Claude Sonnet API integration with exponential backoff retries and input sanitization guardrails
* **Frontend Application**: React, Vite, TypeScript, Zustand, TailwindCSS with curated, harmonious dark-mode HSL styling
* **Containerization & Scale**: Horizontal Pod Autoscaling (HPA) blueprints, lightweight Docker workers, and Kubernetes orchestrations

---

## 🗺️ Hardened Development Journey (Completed)

We have successfully implemented and verified all six core development phases of the BreachReplay system:

* **Phase 0 — Hardened Backend Foundation**: Asynchronous database models, route-level Role-Based Access Control (RBAC), and basic Claude ingestion.
* **Phase 1 — Auth Session Hardening**: Server-side opaque refresh token rotation in Redis and a complete backend Pytest suite with 55 hermetic test cases.
* **Phase 2 — Frontend MVP Hardening**: OIDC-style token refreshes, 401 interception retries, and post-simulation debrief timelines.
* **Phase 3 — Document Ingestion & Admin UI**: Drag-and-drop PDF disclosures ingestion interface, draft review states, and audit log auditing portals.
* **Phase 4 — Collaborative Multiplayer**: Interactive commander seats, participant voting lobbies, presence synchronization, and facilitator custom alert injects.
* **Phase 5 — Debrief & Compliance Reporting**: CISO-level ReportLab PDF generation, NIST SP 800-61 / MITRE ATT&CK coverage maps, and auditor-ready CSV training logs.
* **Phase 6 — Platform Scale**: Resilient database connection pooling, AWS S3 storage streams with local fallbacks, tenant onboarding APIs, subscription upload quotas, and scalable Kubernetes HPA blueprints.

---

## 🔮 Future Enhancements for a World-Class Platform

To move beyond the core architecture and build an industry-leading, enterprise-grade cybersecurity simulator, the following capabilities have been scheduled for development:

### 🎮 1. Advanced Interactive Simulation & Gamification
* **Multi-Branching Decision Trees**: Shift from linear timelines to branching choice paths (e.g., Choose-Your-Own-Adventure format). A team’s containment decision directly changes downstream injects, splitting the narrative into dramatic recovery or active compromise scenarios.
* **Live AI Facilitation**: Integrate a dynamic Claude-powered facilitator that monitors lobby chat logs and injects reactive threat actions based on the team's live communication behavior.
* **Threat Hunting sandbox**: Embed interactive terminal environments or mock packet viewers where players must run real CLI commands to find IOCs (Indicators of Compromise) or identify the malicious IP required to unlock a decision gate.
* **Role-Specific Alert Feeds**: Segment alert feeds by role so that network logs stream to the Network Specialist and media inquiries to the PR Lead, forcing authentic cross-functional collaboration.

### 🛡️ 2. Enterprise Security, SSO & Compliance
* **SAML SSO / OIDC Auth**: Integrate corporate identity federations (e.g., Azure Active Directory, Okta, Ping Identity) to satisfy enterprise onboarding requirements.
* **Immutable Compliance Evidence**: Store CSV and PDF audit packages in read-only WORM storage (e.g., AWS S3 Object Lock) signed with organizational asymmetric private keys, ensuring training logs cannot be retroactively edited.
* **Granular Security Quotas**: Implement advanced, CISO-managed tenant controls over maximum concurrent simulations, analyst seat ceilings, and custom log retention horizons.

### 🔌 3. SIEM & Corporate Integrations
* **SIEM Alert Streaming**: Expose webhooks or syslog relays allowing the simulation engine to stream mock attack alerts directly into the customer's staging SIEM (e.g., Splunk, Microsoft Sentinel). This forces SOC analysts to use their real corporate tools to discover, investigate, and solve the simulated breach.
* **Incident Response Policy RAG**: Leverage pgvector embeddings to index the organization's custom Incident Response guidelines. The Claude debrief engine will then grade the team's tabletop performance *specifically* against their own company playbooks instead of generic NIST frameworks.
* **Extracted Scenario LLM Evaluator**: Insert an automated LLM evaluator (e.g., self-reflection loops) to grade the logical consistency and gameplay quality of new AI-extracted breach documents before they are submitted for administrator publishing.
