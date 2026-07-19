# Nemotron extraction backend — findings and standing policy

`nemotron-3-super-120b-a12b` (NVIDIA NIM, OpenAI-compatible endpoint) is
wired as an alternate SCENARIO EXTRACTION backend in
`backend/app/pipeline/claude_client.py`, gated behind
`settings.EXTRACTION_PROVIDER` (default `"claude"`). Ingestion-only —
never touches `generate_decision_commentary`/`generate_debrief_report`
(runtime paths) or any Claude Code/reviewer/Arena path.

**Standing policy: `EXTRACTION_PROVIDER` stays `"claude"` for any real
ingestion run. Nemotron is candidate-generation only — every identifier it
produces requires manual source verification before it can go into a real
scenario.** This isn't a placeholder restriction pending more testing; it's
the conclusion of the one real evaluation run below.

## Method

Ran the actual `EXTRACTION_PROMPT` (same one Claude's path uses, same
`hidden_iocs` schema) against `CyOTE-Case-Study_Colonial-Pipeline.pdf`
(repo root — the real CISA/INL case study, extracted via `pypdf`, same
library `app/pipeline/tasks.py` uses for real document ingestion), twice:

1. **Unconstrained** — streaming with `chat_template_kwargs: {thinking: true}`,
   `reasoning_content` stripped from `content` per-chunk.
2. **Schema-enforced** — same, plus `response_format={"type":"json_schema",
   ...,"strict":true}` mirroring the full extraction contract, with
   `matches_on` restructured (all four keys present, three null — strict
   mode can't express "exactly one of N optional keys" without that) and
   `mitre_technique` regex-locked to enterprise `T1###`/`T1###.###`.

Both runs' `hidden_iocs` were checked line-by-line against the source PDF's
extracted text (`grep` for the specific IPs/domains/hostnames/numbers each
entry claimed).

## Structural finding: schema enforcement works

Run 1 (unconstrained) drifted the whole contract — `scenario_title` instead
of `title`, `decision_gates`/`question_text` instead of
`decision_tree`/`context_summary`, `pressure_injections` omitted entirely,
and **every** `hidden_ioc` was missing `matches_on`, `severity`,
`timestamp`, and `rule_id` outright.

Run 2 (schema-enforced) came back fully conformant: exact top-level keys,
every `hidden_ioc` field present, `matches_on` correctly resolving to
exactly one non-null key per entry, all `mitre_technique` values in
enterprise `T1xxx` form.

**Caveat:** the source document itself is a CyOTE case study that natively
cites ATT&CK-for-ICS IDs (`T0822`, `T0826`, ...) throughout. Forcing
enterprise `T1xxx` via the schema gets contract conformance, but it's a
translation layer WE impose for cross-scenario consistency — not a more
"correct" reading of an ICS-native source. Run 1's `T0xxx` output was
actually more faithful to the source's own citation convention.

This is now the implementation in `_extract_via_nemotron` — see that
function's constants (`_NEMOTRON_EXTRACTION_SCHEMA` and friends).

## Provenance finding: disqualifying for a drop-in ingestion path

The source PDF contains **zero IP addresses** and never names the
compromised VPN account. Checked every new identifier from both runs
against the extracted source text:

| Claim | Run(s) | Verdict | Source |
|---|---|---|---|
| C2 IP `185.220.101.34` | Both, independently | **Fabricated, recurring** | Zero IP addresses anywhere in the source. The same IP recurring across two independent runs (and coinciding with Claude's own already-fictional choice in `seed.py`) suggests a "stock" TOR-exit IP pulled from general training data, not case-specific knowledge |
| DNS query to `torproject.org` | Run 1 | Fabricated, plausible | TOR-as-C2-channel is real and documented ("Observable 1: Victim Connects to C2 Network via TOR"); this specific artifact is invented |
| TOR ORPort 9001 | Run 1 | Fabricated, plausible | Real default TOR port, zero mentions in source |
| Registry Run-key persistence via `svchost.exe` | Run 1 | Fabricated, wrong technique | `svchost.exe` never appears in source. Source's registry artifacts are a **Services**-key change and SAM entries, not Run-key autostart |
| VPN brute-force (failed logons, EventID 4625) | Run 1 | Wrong framing | Source: "authenticated connection credentials" via a valid account — a successful/valid-account story, not brute-force |
| Ransomware encryption on OT/HMI workstation `WKS-CTRL-07` | Run 2 | **Inverts a documented fact** | Source, explicit: "The OT segments of the network were left intact and operational... Colonial deemed it unsafe to continue... and shut down the pipeline to prevent the spread" — OT was never encrypted, the shutdown was precautionary |
| Exfil size (~100MB/980MB) | Both runs | **Wrong, repeated** | Real documented figure is **100 GB**, stated twice in source — off by 100-1000x in both runs, and internally inconsistent between each run's own `raw_log` and `description` |

Any of these shipping unreviewed would put a fabricated or factually wrong
identifier into a training scenario — the exact provenance risk a
same-domain-doesn't-guarantee-same-facts extraction pipeline has to guard
against.

## What was real — hand-authored into `seed.py`

Two findings were genuinely sourced and were gaps in the existing
hand-authored Colonial Pipeline `hidden_iocs`:

- **Dark-web leaked-credential origin** (Run 2) — CISA/CyOTE "Observable 1:
  Leaked Credentials and Passwords Found On Internet." `svc_backup`'s VPN
  password was found in a public dark-web breach dump and never rotated —
  the real, documented root cause of initial access. Claude's original
  hand-authored set never captured this; it only had generic "successful
  login" entries. Added as `rule_id: TI-004`.
- **`vssadmin` shadow-copy deletion, granular process-level record** — real,
  documented ("Observable 2: Removes Volume Shadow Copies"), but was only
  present as an aggregate `alert_sequence` entry (`EDR-091`, 26-host
  summary), never as a `hidden_ioc` a player could earn by pivoting on the
  process name specifically. Added as `rule_id: SYSMON-042`.

Both cite the specific source PDF line numbers in a code comment directly
above their `seed.py` entries.

## Takeaway

Nemotron's kill-chain elaboration is richer than Claude's in places, and it
found two real details Claude's extraction missed — it's not a bad model.
But two runs, same document, both invented the same specific C2 IP, and one
run inverted a documented fact about which network segment was actually
encrypted. That failure rate is why this backend gets a flag, not a
fallback path: it stays candidate-generation only, reviewed line-by-line
against source before anything from it ships.
