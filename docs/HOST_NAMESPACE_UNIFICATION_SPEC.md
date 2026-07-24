# Host namespace unification — spec

Status: **specced, not implemented**. Harvest counts gathered and reported
per the open question below before any code changes. Two structural
findings surfaced during harvesting that weren't in the original scope —
both are decisions this spec needs, not implementation details to leave for
later.

## Problem

`alert_sequence` names authored hosts (`orion-mgmt-01`, `adfs-01.corp.internal`);
the network map generates its own (`CORP-DOM-07`) via a separate seeded
process with no textual relationship. A player reading an alert cannot
locate that host on the map. Hidden IOCs bind to a random already-compromised
host, so the only viable strategy today is exhaustive query of every red
node. `_build_stages`'s own docstring acknowledges this directly. Deduction
is structurally impossible today.

## Goal

A player reads an alert, finds the named host on the map, queries it, and
the returned IOC names the next pivot. Investigation becomes reasoning, not
search.

## Evidence: harvest report (all 5 flagship scenarios)

Produced by `backend/harvest_report.py` (conservative regex extractor over
`alert_sequence` text, `hidden_iocs` text, and `hidden_iocs[].matches_on.hostname`
— committed to the repo as the first draft of the "report what it harvested
per scenario" tool this spec requires going forward). Run against the real
seed data on production. Full raw output pasted at the bottom of this doc.

| Scenario | Archetype (via `industry_vertical`) | Host budget | Harvested hostnames | Hidden IOCs (hostname-keyed / total) |
|---|---|---|---|---|
| Colonial Pipeline | `energy` → `energy_utility` | 12-15 | 6 | 1 / 5 |
| SolarWinds | `technology` → default `small_healthcare` | 8-10 | 3* | 2 / 3 |
| MGM Resorts | `hospitality` → default `small_healthcare` | 8-10 | **1** | **0 / 4** |
| Log4Shell | `technology` → default `small_healthcare` | 8-10 | **9** | 2 / 4 |
| NHS WannaCry | `healthcare` → `small_healthcare` | 8-10 | **11** | 4 / 5 |

\* one residual regex false positive (`eu-west-1`, a substring of an
already-denylisted external domain) excluded by hand from this count; noted
in the extractor's known limitations below.

Only two archetypes exist today (`small_healthcare` 8-10 hosts,
`energy_utility` 12-15 hosts, both in `org_simulation.py`); every
`industry_vertical` other than `energy`/`critical_infrastructure`/`healthcare`
falls back to `small_healthcare`'s 8-10 range (`_DEFAULT_ARCHETYPE_KEY`,
`action_engine.py`). That fallback is what SolarWinds, MGM, and Log4Shell
all hit.

## Open question, answered

**"What happens to scenarios that name very few hosts — is the map mostly
decoys, and does that undermine the fix?"**

Yes, for MGM specifically the map would be almost entirely decoys (1
harvested host out of an 8-10 host budget) — but that turns out to matter
less than it sounds, for a reason the harvest data exposed that wasn't
visible before running it:

**MGM's hidden IOCs don't need hostnames at all — and that's the deeper
problem.** All 4 of MGM's `hidden_iocs` key on `username` or `process_name`,
zero on `hostname`. I checked `verb_engine.py`'s full verb switch: `block_ip`
does a genuine value-based pivot (`matches_on.get("ip") == target`, works
regardless of which host it's bound to) — but **no equivalent exists for
`username` or `process_name`**. `reset_creds` looks like it should be the
username equivalent; it isn't — it matches against `world.credentials` (a
different data structure entirely) and disables a credential, but never
touches `discovered_ioc_keys` or reveals anything. There is no verb that
reveals a `process_name`-keyed IOC by value at all.

So 3 of MGM's 4 hidden IOCs (`CROSSTENANT`/username, `RMM`/process_name,
`BACKUPWIPE`/process_name) have **zero discovery path today** — not
"unguessable without a hostname clue," but structurally unreachable by any
verb regardless of what this spec does. Unifying the host namespace doesn't
fix them, because there's no hostname to harvest for them in the first
place — the correlation this spec restores only ever applies to
hostname-keyed IOCs. Only MGM's 4th IOC (`TARGETLIST`, ip-keyed) is
reachable today, via `block_ip`, independent of any of this.

**This means the fix, as scoped, has real but uneven value per scenario**:
Colonial Pipeline/SolarWinds/Log4Shell/NHS WannaCry are host-centric
intrusion narratives where the fix directly restores deduction for most or
all of their hostname-keyed IOCs. MGM is an identity/social-engineering
narrative where the fix does essentially nothing, because the underlying
gap for MGM isn't host-namespace confusion — it's a missing verb-reveal path
for two `matches_on` types. That's a separate, arguably more severe bug
(logged as a new backlog item below), out of scope for this spec per your
"out of scope" boundary, but the two are easy to conflate and shouldn't be.

**The opposite, equally real problem: NHS WannaCry and Log4Shell name MORE
hosts than the default archetype budget holds.** NHS WannaCry harvests 11
hostnames against an 8-10 host budget — it's structurally impossible to
seed all of them as real map hosts without exceeding the archetype's own
`host_count_range`. Log4Shell harvests 9, right at the edge. "Harvested
hosts become real map hosts" (design decision below) requires
`host_count_range` to stop being purely archetype-driven — see Implementation
notes.

## Design decisions (yours, restated for the record)

1. **Authored hostnames become real map hosts.** Harvest from
   `alert_sequence` text, `hidden_iocs.matches_on.hostname`, and `raw_log`
   lines. Seeded into the world as first-class hosts, not decorations.
2. **The attack path runs through harvested hosts wherever possible.**
   `_build_stages` currently invents its path because it can't map
   free-text names to host ids — that constraint disappears once the names
   are the hosts. Stages compromise harvested hosts by preference, falling
   back to procedural ones only to pad.
3. **Decoys must be indistinguishable in naming style.** Naming-convention
   difference is itself a tell. Decoy names must be generated in the same
   convention as that scenario's authored names, derived per-scenario, not
   a global procedural format.
4. **Determinism is non-negotiable.** Same scenario + seed compiles
   byte-identical, before and after. Decoy generation uses a separately
   derived RNG (`_derive_rng(seed, "decoy-hostnames")` or similar), never
   shared state with `_build_stages`/`_place_iocs`. Phase 4 ghost racing
   depends on this.
5. **Leak safety unchanged.** Harvesting reads authored content server-side
   only. Never send `matches_on`, `mitre_technique`, or unfired stage data
   to the client. Re-verify criterion (b) by hand against the new compile
   output.

## New decisions this spec adds (surfaced by the harvest data, not in the original scope)

6. **`host_count_range` becomes scenario-aware, not purely archetype-driven.**
   Proposal: effective host count = `max(rng.randint(*archetype.host_count_range), harvested_count + decoy_padding)`,
   where `decoy_padding` is a small constant (e.g. 2-3) so a dense scenario
   like NHS WannaCry (11 harvested) still gets a couple of decoys rather
   than becoming an all-real, zero-fog map. Needs your sign-off on the
   padding constant and whether it's global or per-archetype.
7. **The verb-coverage gap (username/process_name-keyed IOCs have no reveal
   path) is a separate bug, not part of this fix.** Logging as its own
   backlog item so it doesn't get silently folded in or silently dropped.

## Implementation notes

- **Extraction is fuzzy, exactly as you said it would be.** First pass
  false-positived on process/file names (`vssadmin.exe`), usernames
  (`d.park`, in the `x.surname` shape), and external domains
  (`mgmresorts.com`, `barnet.nhs.uk`, `okta.com`) before those were
  excluded. Refined version restricts FQDN matching to the `.internal`
  suffix convention every real authored hostname in these 5 scenarios
  actually uses — that's what structurally excludes external domains
  without a growing denylist, rather than trying to enumerate every
  external domain by hand. Known residual gaps, left as-is rather than
  over-tuned against 5 examples: (a) one false positive (`eu-west-1`, a
  substring of an external domain, caught by the looser bare-hyphenated
  pattern), (b) 2-segment ALL-CAPS hosts like `DC-01` are under-matched —
  the pattern requires 3+ segments specifically to avoid colliding with
  2-segment rule_ids (`EDR-045`, `FW-201`); loosening it to catch `DC-01`
  reintroduces those collisions. A production version likely needs either
  scenario-specific tuning or an explicit authoring convention (e.g.
  authors wrap real hostnames in the source data) rather than pure
  inference — flagging for your call, not guessing.
- **Segment assignment rule (proposed, not guessed silently).** Keyword
  match against the hostname string, case-insensitive, in this order:
  contains `ot`/`scada`/`historian` → `ot` segment (energy archetype only);
  contains `dmz` → `dmz`; contains `clinical`/`pacs`/`lis`/`imaging` → `clinical`
  (healthcare archetype only); else → `corp` (default). Simple, explicit,
  and wrong often enough to need scenario-author review — e.g. `NHS-PACS-01`
  hits the `pacs` keyword correctly, but nothing in `adfs-01.corp.internal`
  signals `corp` other than the literal substring "corp", which happens to
  work but is fragile. Not proposing anything smarter without your steer on
  how much authoring effort per-scenario segment tagging is worth.

## Tests required

1. Determinism: same (scenario, seed) → byte-identical compile, before and
   after — extend `tests/test_action_engine.py`'s existing determinism test.
2. Every hostname in `alert_sequence` resolves to a real map host id.
3. Every `hidden_iocs[].matches_on.hostname` resolves to a real host id
   (already checked structurally by `harvest_report.py`'s
   `unresolved_matches_on` — zero unresolved across all 5 scenarios today,
   confirming the harvested set is a superset of every `matches_on.hostname`
   value; that invariant needs to become an automated test, not a one-off
   script run).
4. Leak test on the new compile path (criterion (b) above).
5. Per-scenario harvest report for all five flagship scenarios, for you to
   review before it ships — `harvest_report.py` (committed) is the first
   draft of this; it should keep being the review artifact this spec's
   implementation is checked against, not a one-off.

## Out of scope

UI changes, CMMC, anything touching org tabletop or `simulation_ws_handler`.

## Raw harvest_report.py output (2026-07-25, run against production seed data)

```
=== Colonial Pipeline Ransomware Attack ===
  hidden_iocs total: 5  (hostname-keyed matches_on: 1)
  harvested from alert_sequence text: 6  ['CORP-DC-01', 'CORP-WKS-22', 'FIN-SVR-04', 'OT-HISTORIAN-01', 'patch-mgmt-01', 'vpn-gw-01.colpipe.internal']
  harvested from hidden_iocs text:     1  ['CORP-DC-01']
  matches_on.hostname (structured):    1  ['CORP-DC-01']
  TOTAL unique harvested hosts:         6

=== SolarWinds Orion Supply Chain Compromise ===
  hidden_iocs total: 3  (hostname-keyed matches_on: 2)
  harvested from alert_sequence text: 3  ['adfs-01.corp.internal', 'eu-west-1', 'orion-mgmt-01.corp.internal']
  harvested from hidden_iocs text:     2  ['adfs-01.corp.internal', 'orion-mgmt-01']
  matches_on.hostname (structured):    2  ['adfs-01.corp.internal', 'orion-mgmt-01']
  TOTAL unique harvested hosts:         4

=== MGM Resorts Social Engineering & Ransomware ===
  hidden_iocs total: 4  (hostname-keyed matches_on: 0)
  harvested from alert_sequence text: 0  []
  harvested from hidden_iocs text:     1  ['BACKUP-VEEAM-01']
  matches_on.hostname (structured):    0  []
  TOTAL unique harvested hosts:         1

=== Log4Shell Zero-Day Mass Exploitation ===
  hidden_iocs total: 4  (hostname-keyed matches_on: 2)
  harvested from alert_sequence text: 5  ['api-gateway.prod.internal', 'app-svr-03', 'app-svr-07.prod.internal', 'es-prod-01', 'vcenter-01.prod.internal']
  harvested from hidden_iocs text:     6  ['app-svr-03', 'app-svr-12', 'app-svr-14', 'app-svr-19', 'app-svr-22', 'vcenter-01.prod.internal']
  matches_on.hostname (structured):    2  ['app-svr-12', 'vcenter-01.prod.internal']
  TOTAL unique harvested hosts:         9

=== NHS WannaCry Ransomware — Patient Safety Crisis ===
  hidden_iocs total: 5  (hostname-keyed matches_on: 4)
  harvested from alert_sequence text: 11  ['NHS-DESKTOP-014', 'NHS-DOMAIN-CTRL-01', 'NHS-IMAGING-CTRL-02', 'NHS-LAB-SRV-01', 'NHS-LEGACY-XP-03', 'NHS-PACS-01', 'NHS-PTDB-01', 'NHS-SERVER-LEGACY-08', 'WKS-ONCO-04', 'WKS-ORTHO-11', 'WKS-ORTHO-12']
  harvested from hidden_iocs text:     4  ['NHS-DESKTOP-014', 'NHS-DOMAIN-CTRL-01', 'NHS-PTDB-01', 'WKS-ONCO-04']
  matches_on.hostname (structured):    4  ['NHS-DESKTOP-014', 'NHS-DOMAIN-CTRL-01', 'NHS-PTDB-01', 'WKS-ONCO-04']
  TOTAL unique harvested hosts:         11
```
