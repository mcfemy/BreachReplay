# Phase 2.5 — CMMC Evidence Layer

**Status:** approved, ready to build.
**Buyer:** consultant-first (RPO / CMMC consultant), contractor second.
**Governing principle:** compliance is an **export**, never an experience. The game does not change. The evidence materialises afterward.

---

## 1. Why this exists

NIST SP 800-171 control **3.6.3 — "Test the organizational incident response capability"** requires contractors to test IR, not merely document a plan. Public guidance is explicit that acceptable methods include *"checklists, walk-through or tabletop exercises, simulations (both parallel and full interrupt), and comprehensive exercises."* A BreachReplay session is a simulation. It already produces most of what the control wants, and with better fidelity than a tabletop: real timestamps, real decisions, real sequencing.

**The evidence bar, from a Lead CMMC Certified Assessor** (Carter Schoenberg, VP Assessment & Compliance, SoundWay Consulting):

1. Scenario for exercise
2. List of all who attended
3. Timelines of every aspect of what occurred
4. Validation of internal and external contact communications
5. Lessons learned
6. Proof lessons learned applied to the latest version of the IRP

On item 4 he clarified: *"There is no requirement to do sequentially. You just have to prove it was done. Having said that, an escalation path should very much be in play because otherwise people may be notified that shouldn't be."*

That resolves two things. The session's own notification decisions **can** carry item 4 — no separate real-world channel validation required. And over-notification is a named failure mode, which has a design consequence (§10).

**The control's own discussion text**, independently confirming the mechanic already shipped:

> *"Incident response testing can also include a determination of the effects on organizational operations (e.g., reduction in mission capabilities), organizational assets, and individuals due to incident response."*
> *"Any negative impacts to the normal day-to-day operations when responding to an incident should also be identified and documented."*

That is exactly what Proportionate Response measures. `OVERREACTED` and the collateral breakdown are the control's own language, computed automatically. **This is the strongest single claim the product has for this market.**

**Division of responsibility.** The session proves what a simulation can prove: scenario, participants, timeline, decisions, notifications, outcome, operational impact. The organisation declares what only it can know: its notification obligations, its lessons learned, its IRP version. The report shows both and never presents a declaration as if the system verified it.

---

## 2. What the session already produces

No new instrumentation. These exist today:

| Evidence item | Source |
|---|---|
| Scenario + real-incident provenance | `Scenario` (title, `source_reference`) |
| Participants | `ActionRun.user_id` / org session participants |
| Full decision timeline | `action_log` — every verb, target, cost, timestamp |
| Notification decisions | `escalate` actions in `action_log` |
| Outcome | `determine_outcome` — five graded states |
| Operational impact of the response | collateral breakdown with authored weights |
| Evidence discovered | `discovered_ioc_keys` |
| Time to containment | `elapsed_seconds` at final containment |

The build is **assembly and attestation**, not capture.

---

## 3. Scope

**In scope:** multi-tenant org model; multi-run evidence sessions; evidence pack (PDF); org notification matrix; after-action workflow; signing and verification; consultant branding; control mapping (3.6.3 primary, 3.6.1/3.6.2/AT-family where genuinely exercised).

**Out of scope:** any change to gameplay, verbs, scoring or console UI; Arena; CUI-specific scenarios (ship against existing content — the control cares that IR was tested, not that the scenario involved CUI); automated verification of org declarations.

---

## 4. Multi-tenancy

Structural from day one.

```
ConsultingOrg (the RPO)
  └── ClientOrg (the contractor being assessed)
        ├── Members (the client's people, who play)
        └── EvidenceSession (one exercise — MAY SPAN MULTIPLE RUNS)
              └── ActionRun[]  (one per participant)
```

**Models:** `ConsultingOrg` (name, branding, members); `ClientOrg` (belongs to a ConsultingOrg; name, POC, notification matrix, IRP reference); `EvidenceSession` (belongs to a ClientOrg, links **many** `ActionRun`s, holds after-action data); `Membership` (user ↔ org, role: `consultant_admin` | `client_participant`).

**Multi-run is required, not optional.** A real tabletop is a team exercising together. An evidence session aggregates every participant's run into one exercise: one scenario, several people, one artifact. Build the many-to-one relationship from the start — retrofitting it means a schema change.

Aggregation rules for a multi-run session:
- Timeline merges all participants' actions into one chronological sequence, attributed by name
- Outcome is reported **per participant**, plus a session-level summary — do not average graded states into a single meaningless label
- Collateral is reported per participant and as a session total
- Notification decisions are pooled: who was notified, by whom, when

**Isolation is a blocking requirement.** A consultant sees only their own client orgs; a client participant sees only their own runs. Cross-tenant leakage is the highest-severity failure mode in this layer. Explicit tests required.

---

## 5. Notification matrix and notification evidence

800-171 imposes a duty to notify *external authorities* generically. It does not name DC3 — that comes from **DFARS 252.204-7012**. Insurers and primes come from contracts. The list is org-specific and must be declared.

Per `ClientOrg`:

| Field | Meaning |
|---|---|
| `authority` | DC3, CISA, prime contractor, cyber insurer, internal exec |
| `basis` | DFARS 252.204-7012, contract clause, policy |
| `channel` | DIBNet portal, phone, email |
| `window` | required timeframe, e.g. 72 hours |
| `last_validated` | optional — date the channel was last exercised for real |
| `validation_note` | optional free text |

**Per Carter's answer, the session's own notification decisions satisfy item 4.** The pack presents them together with the matrix: who the exercise notified, when, and how that maps to the org's declared obligations. `last_validated` is useful context (a "DC3 — never validated for real" note is genuinely informative to an assessor) but is **not** a required attestation.

The report still distinguishes computed facts from declared ones — the timeline is what the system observed; the matrix is what the org states.

---

## 6. After-action workflow (items 5 and 6)

A session cannot produce lessons learned or prove they reached the IRP. Public guidance names the loop: *"Produce a time-stamped AAR with artifacts; track remediation items to closure; update playbooks and training; map results back to IR.L2-3.6.3."*

So the pack is a **workflow the org completes**, not a file the system emits.

- **Lessons learned** — free-text entries, each optionally anchored to a moment in the run (a verb, decision, or stage). Timestamped and attributed.
- **Remediation items** — owner, due date, status (`open`/`closed`), closure note. Open items appear in the pack; this is the POA&M linkage assessors expect.
- **IRP linkage** — IRP name/version/date, and per lesson whether it was incorporated (yes/no/N-A) with a note. This is an **attestation**: recorded, not verified.
- **Sign-off — both parties.** The client attests the record is accurate; the consultant attests to facilitation. Both named and timestamped. No final pack generates before both signatures.

---

## 7. The evidence pack

A PDF. Sections in order:

1. **Cover** — consultant branding, client org, exercise date, controls addressed, document ID
2. **Exercise summary** — scenario, real-incident provenance with citation, mode, duration, timezone-qualified date
3. **Participants** — names, roles, org
4. **Timeline** — merged chronological sequence across all participants, attributed, with the attacker's stage progression alongside. Strongest section; make it readable, not a raw dump
5. **Outcomes** — per participant, graded state with plain-language explanation, plus session summary
6. **Operational impact of the response** — systems taken offline unnecessarily, with significance. Quote the control's own "effects on organizational operations" language so the mapping is immediate
7. **Evidence discovered** — indicators found, and missed
8. **Notifications** — decisions taken in the exercise, mapped against the declared matrix
9. **Lessons learned and remediation** — with owners and status
10. **IRP linkage** — version, per-lesson incorporation, attestation
11. **Control mapping** — each section mapped to the control it evidences. Anything not genuinely exercised marked *not evidenced by this exercise* rather than padded
12. **Attestation and signatures** — both signers, timestamps, document hash

**Tone:** assessor-facing, plain, no marketing. Where the artifact cannot prove something, it says so. Overclaiming is fatal with a buyer whose job is verification.

---

## 8. Signing and tamper-evidence

SHA-256 over canonical document content, signed with a service key, hash and verification URL in the footer. A public endpoint takes document ID + hash and confirms whether it matches an issued pack.

The claim is precise: **this artifact was issued by BreachReplay for this session on this date and has not been altered since.** Not a claim that the org's declarations are true — state that distinction in the document.

Private key in environment config, never in the repo, rotatable without invalidating past verifications (store a key ID per issued document).

---

## 9. Boundaries

- **No compliance language on the play surface.** Same run, same tension, same UI. If a player can tell they are in "compliance mode," the design has failed.
- **No gameplay changes.** Zero edits to verbs, scoring, the console, or `simulation_ws_handler`.
- **Computed vs declared stays visually and textually distinct.**
- **Multi-tenant isolation is blocking**, not best-effort.

---

## 10. Related Phase 3 item (log, do not build here)

Carter: *"an escalation path should very much be in play because otherwise people may be notified that shouldn't be."*

Over-notification is a real failure mode — telling the prime, the insurer and DC3 about a false positive has commercial and legal consequences. Today `escalate` is an untargeted 0-second action. It should become a decision about **who** to notify, drawn from the org's matrix, with a cost for notifying parties the incident doesn't warrant — proportionality applied to communication, exactly as Proportionate Response applied it to containment.

That makes the notification evidence meaningful rather than a checkbox. **Log to BACKLOG as a Phase 3 tuning item.** It is not part of this build, but the evidence layer is more valuable once it lands.

---

## 11. Build order

1. Multi-tenancy models, migration, isolation tests
2. Consultant/client onboarding and invitation flow
3. `EvidenceSession` designation from completed runs (multi-run aggregation)
4. Notification matrix CRUD
5. After-action workflow (lessons, remediation, IRP linkage, dual sign-off)
6. PDF generation
7. Signing and verification endpoint
8. Consultant branding

Ship 1–3 before 6. The pack is worthless without correctly-scoped, correctly-isolated session data behind it.

**Metering note:** pricing shape is undecided. Meter **evidence packs generated per client org** — that supports per-org, per-pack, or seat pricing later without a data change.

---

## 12. What this is worth

Every RPO has clients who must evidence 3.6.3. Most evidence it with a slide deck and a memory. This produces a timestamped, signed, control-mapped artifact from an exercise people actually want to do — and, because of Proportionate Response, it evidences the operational-impact clause that almost nobody else captures at all.

That last part is not a marketing line. It is in the control's discussion text, it is computed automatically, and it fell out of a game-design decision made before anyone went looking for it.
