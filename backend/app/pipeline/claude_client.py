import re
import time
import anthropic
import json
from app.core.config import settings
from app.core.logging import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential, RetryCallState, retry_if_exception

# ── Gemini fallback setup ──────────────────────────────────────────────────────
try:
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as _genai
    if settings.GEMINI_API_KEY:
        _genai.configure(api_key=settings.GEMINI_API_KEY)
        _gemini_model = _genai.GenerativeModel(settings.GEMINI_MODEL)
        _gemini_flash = _genai.GenerativeModel("gemini-2.5-flash")
    else:
        _gemini_model = None
        _gemini_flash = None
except ImportError:
    _genai = None
    _gemini_model = None
    _gemini_flash = None

# ── Nemotron (NVIDIA NIM) extraction-only setup ───────────────────────────────
# Alternate SCENARIO EXTRACTION backend, gated by settings.EXTRACTION_PROVIDER
# == "nemotron" (see extract_scenario_from_document below). OpenAI-compatible
# endpoint — never touches generate_decision_commentary/generate_debrief_report
# (runtime paths) or any Claude Code/reviewer/Arena path.
#
# CANDIDATE-GENERATION ONLY — settings.EXTRACTION_PROVIDER defaults to
# "claude" and should stay that way for any real ingestion run. Verified
# against the actual Colonial Pipeline source document (two runs, one
# schema-enforced): the model invented the same C2 IP in both independent
# runs, fabricated plausible-but-uncited artifacts (a TOR domain, a specific
# ORPort, a Registry Run-key persistence mechanism), and in one entry
# inverted a documented fact (claimed OT/HMI ransomware encryption; the
# source is explicit that OT was left intact). It also surfaced two real,
# correctly-sourced findings Claude's extraction had missed. Full writeup,
# including the two now hand-authored into seed.py's Colonial Pipeline
# hidden_iocs: docs/NEMOTRON_EXTRACTION_FINDINGS.md. Every identifier
# Nemotron produces requires manual source verification before it can be
# used in a real scenario — this backend does not get an autonomous
# ingestion path.
try:
    from openai import OpenAI as _OpenAI, AuthenticationError as _OpenAIAuthError, BadRequestError as _OpenAIBadRequestError
    _nvidia_client = _OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=settings.NVIDIA_API_KEY) if settings.NVIDIA_API_KEY else None
except ImportError:
    _OpenAI = None
    _OpenAIAuthError = None
    _OpenAIBadRequestError = None
    _nvidia_client = None

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
logger = get_logger(__name__)


def _before_claude_retry(retry_state: RetryCallState) -> None:
    if retry_state.attempt_number > 1:
        retry_state.kwargs["_is_retry_attempt"] = True


def _is_retryable_claude_error(exc: BaseException) -> bool:
    """Don't retry on billing/auth errors — only on rate limits and transient 5xx."""
    if isinstance(exc, anthropic.BadRequestError):
        return False
    if isinstance(exc, anthropic.AuthenticationError):
        return False
    return True


def _is_retryable_nemotron_error(exc: BaseException) -> bool:
    if _OpenAIBadRequestError is not None and isinstance(exc, _OpenAIBadRequestError):
        return False
    if _OpenAIAuthError is not None and isinstance(exc, _OpenAIAuthError):
        return False
    return True


# ── Prompt-injection sanitization ─────────────────────────────────────────────
_MAX_DOC_CHARS = 200_000
_CTRL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_INJECTION_TAG_RE = re.compile(
    r'</?(?:extracted|debrief|document|system|human|assistant)\b[^>]*>',
    re.IGNORECASE,
)


def _sanitize_document(text: str) -> str:
    text = _CTRL_CHAR_RE.sub('', text)
    text = _INJECTION_TAG_RE.sub('', text)
    if len(text) > _MAX_DOC_CHARS:
        text = text[:_MAX_DOC_CHARS]
    return text


def _extract_tagged_json(raw: str, tag: str) -> dict:
    """Extract JSON from <tag>…</tag>. Falls back to markdown fence stripping for Gemini."""
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    open_pos = raw.find(open_tag)
    end_pos = raw.find(close_tag)
    if open_pos != -1 and end_pos != -1:
        content = raw[open_pos + len(open_tag):end_pos].strip()
    else:
        md_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        content = md_match.group(1).strip() if md_match else raw.strip()
    return json.loads(content)


def _call_gemini(prompt: str, model, max_tokens: int = 8192) -> str:
    if model is None:
        raise RuntimeError("Gemini not configured — set GEMINI_API_KEY in .env")
    response = model.generate_content(
        prompt,
        generation_config=_genai.types.GenerationConfig(max_output_tokens=max_tokens),
    )
    return response.text


EXTRACTION_PROMPT = """You are a cybersecurity incident analyst reconstructing a real breach as a high-pressure 45-minute training simulation.

I will provide a breach disclosure document. Your job is to extract and reconstruct this incident so a SOC team experiences the same chaos, time pressure, incomplete information, and executive interference that the real responders faced — compressed into 45 minutes.

<document>
{document_text}
</document>

MANDATORY REQUIREMENTS — do not reduce these:
- MINIMUM 12 decision gates spread across the 45-minute timeline (gate every 3-4 minutes)
- MINIMUM 20 alerts in alert_sequence — mix real indicators with false positives and red herrings
- MINIMUM 6 pressure_injections (CEO emails, legal calls, board demands, breaking news)
- MINIMUM 4 hidden_iocs — real evidence from the document that never appears in alert_sequence
- Every gate has countdown_seconds between 30-75 (shorter = more pressure, use 30 for critical)
- Alert timestamps should be dense and overlapping — multiple alerts per minute at peak

Return ONLY valid JSON inside <extracted> tags:

<extracted>
{{
  "title": "Descriptive incident title",
  "incident_date": "YYYY-MM-DD or null",
  "incident_duration_hours": number or null,
  "initial_access_vector": "phishing|credential_theft|unpatched_cve|supply_chain|insider_threat|social_engineering|physical|unknown",
  "industry_vertical": "healthcare|energy|finance|government|technology|retail|education|other",
  "difficulty": "awareness|practitioner|expert",
  "affected_asset_types": ["list", "of", "asset", "types"],
  "mitre_techniques": ["T1566", "T1078"],
  "nist_controls": ["DE.AE-1", "RS.CO-2"],
  "regulatory_frameworks": ["HIPAA"],
  "extraction_confidence": 0.0,

  "alert_sequence": [
    {{
      "timestamp": "+0m",
      "severity": "critical|high|medium|low",
      "source_system": "SIEM|EDR|Firewall|Auth|DLP|CASB|Network|NOC|Endpoint|Email",
      "rule_id": "RULE-001",
      "description": "Alert exactly as it would appear on a real SOC dashboard — specific, technical, actionable",
      "raw_log": "src_ip=10.0.0.1 user=admin proc=lsass.exe bytes=94000000 dst=185.220.101.34"
    }}
  ],

  "hidden_iocs": [
    {{
      "matches_on": {{"ip": "185.220.101.34"}},
      "timestamp": "+1m",
      "severity": "medium",
      "source_system": "Auth|EDR|Zeek|CloudTrail|Okta|VPN Gateway|IAM|DNS (pick whatever this document's own environment actually used)",
      "rule_id": "AUTH-009",
      "description": "What a SOC analyst would see if they pivoted an investigation on this exact ip/hostname/username/process_name — written as a real finding, not a summary",
      "raw_log": "auth=success user=svc_backup src_ip=185.220.101.34 service=legacy_ftp_portal geo=RU",
      "mitre_technique": "T1078"
    }}
  ],

  "pressure_injections": [
    {{
      "id": "pressure-001",
      "trigger_timestamp": "+8m",
      "type": "email|call|news|sms|slack",
      "from": "Sarah Chen, CEO <s.chen@company.com>",
      "subject": "RE: URGENT - What is happening??",
      "body": "I am getting calls from board members. The Wall Street Journal just contacted our PR team. I need to know right now: are we paying the ransom? What is our exposure? Status in 10 minutes or I am calling the FBI myself. Do NOT let this get to the press before we have a statement ready.",
      "countdown_seconds": 30
    }}
  ],

  "decision_tree": [
    {{
      "id": "gate-001",
      "trigger_timestamp": "+5m",
      "countdown_seconds": 60,
      "urgency_level": "medium",
      "gate_difficulty": "awareness",
      "context_summary": "SITUATION: [exactly what is happening right now — be specific, use real system names, IPs, usernames from the incident]. SIMULTANEOUS PRESSURE: [what else is happening — boss calling, legal on hold, another alert just fired]. INCOMPLETE INFO: [what you do NOT know yet]. DECIDE NOW:",
      "options": [
        {{"text": "Isolate affected hosts from the network immediately via EDR console", "consequence_if_chosen": "Lateral movement halted but attacker is alerted — may destroy evidence or accelerate encryption"}},
        {{"text": "Continue passive monitoring to map full blast radius before acting", "consequence_if_chosen": "Full scope identified in 8 minutes but 14 more hosts compromised during observation window"}},
        {{"text": "Notify CISO and wait for executive authorization before any action", "consequence_if_chosen": "30-minute delay. Attacker reaches domain controller. Game over for containment."}}
      ],
      "correct_index": 1,
      "consequence_if_wrong": "Specific cascading consequence — attacker reaches X, now gate-005 becomes harder",
      "consequence_if_correct": "What a correct fast decision achieves — quantified where possible",
      "rationale": "NIST SP 800-61 RS.MI-2 requires immediate isolation upon confirmed compromise. The real team waited 4 hours and it cost them $4.4M.",
      "nist_control_ref": "RS.MI-2",
      "mitre_technique": "T1021"
    }}
  ]
}}
</extracted>

REALISM RULES:
1. Gates must reference prior decisions — wrong choice at gate-001 must make gate-005 explicitly harder
2. Pressure injections must arrive at the worst moments — during active decision gates
3. Include 3-4 false positive alerts that waste analyst attention (unrelated to the actual breach)
4. Include conflicting information across 2 alerts that the analyst must resolve
5. context_summary must feel like a live SOC call — chaotic, specific, time-pressured
6. All three options at every gate must seem plausible under pressure — no obvious wrong answers
7. Use real technical details from the source document; extrapolate realistically when needed

HIDDEN_IOCS — real evidence that rewards investigation instead of just reacting to the alert feed:
- Every entry must be something the source document actually documents or clearly implies (an
  attacker IP, a compromised hostname, an abused account, a malicious process) — never invented
  from nothing. If the document names a real C2 IP, malware hash, or domain, use the REAL value.
- `matches_on` is the pivot key: exactly one of {{"ip": "..."}}, {{"hostname": "..."}},
  {{"username": "..."}}, {{"process_name": "..."}} — the literal value from the document that an
  analyst would type into an investigation panel to surface this entry.
- `raw_log` must be written in that entry's OWN source system's real log format, not generic
  prose describing what happened:
  - Windows Security/Sysmon: real Event IDs and field names, e.g.
    `event=4624 user=jsmith logon_type=3 src_ip=185.220.101.34` (4624=logon),
    `event=4688 new_proc=powershell.exe cmdline=-enc<b64> parent=outlook.exe` (4688=process creation)
  - Zeek conn.log-style network evidence: `id.orig_h=10.0.4.12 id.resp_h=185.220.101.34
    id.resp_p=443 proto=tcp service=ssl duration=812.4 orig_bytes=48200 resp_bytes=910000000
    conn_state=SF`
  - AWS CloudTrail-style cloud evidence: `eventName=AssumeRoleWithSAML
    eventSource=sts.amazonaws.com sourceIPAddress=185.220.101.34
    userIdentity.arn=arn:aws:sts::111122223333:assumed-role/AdminAccess/svc_backup
    awsRegion=us-east-1`
  - Match the source_system to whatever the document's own environment actually is — do not
    force CloudTrail onto an on-prem-only incident.
- `mitre_technique` is the ATT&CK technique this specific piece of evidence demonstrates — it can
  differ from the decision_tree gate it's near, since one gate often has multiple techniques in
  play (e.g. the gate is about lateral movement, T1021, but this IOC is the credential-dumping
  evidence, T1003, that enabled it).
- Each hidden_ioc should connect to something already in alert_sequence (the same IP, the same
  account, the same host) — the reward for pivoting is confirming a hunch the visible feed only
  hinted at, not a disconnected fact.

OVERALL SCENARIO DIFFICULTY — set the top-level "difficulty" field based on how demanding the incident is as a whole:
- "awareness": Single attack vector, slower pace, mostly clear-cut decisions — suited to teams new to IR tabletop exercises
- "practitioner": Multi-stage attack with lateral movement and competing pressures — suited to working SOC analysts
- "expert": Multi-domain incident (IT/OT, regulatory, executive, law-enforcement) with no clean answers — suited to seasoned IR leads
This must reflect the actual incident's complexity — do not default to "practitioner" for every scenario.

PROGRESSIVE DIFFICULTY — gates must escalate:
- Gates 1-3 (gate_difficulty: "awareness"): One option is clearly wrong; early detection decisions; countdown 60-75s
- Gates 4-7 (gate_difficulty: "practitioner"): All options are plausible; technical triage under pressure; countdown 45-60s
- Gates 8-10 (gate_difficulty: "expert"): All options carry real risk; legal/regulatory trade-offs; countdown 30-45s
- Gates 11+ (gate_difficulty: "critical"): No safe option; irreversible decisions; countdown 25-35s

CORRECT_INDEX DISTRIBUTION — this is mandatory:
- NEVER use correct_index: 0 for more than 2 consecutive gates
- Distribute correct answers so that across 12 gates, roughly 4 are index 0, 4 are index 1, 4 are index 2
- The example above uses correct_index: 1 — vary this across ALL gates
- Wrong answers must still be tempting under pressure — never make the wrong options obviously bad

Timestamps use format +Xm (e.g. +0m, +3m, +7m, +12m). Keep them unique across alert_sequence. Decision gate trigger_timestamps must match an alert timestamp exactly."""


DEBRIEF_PROMPT = """You are a senior incident response consultant generating a post-simulation debrief report.

Scenario: {scenario_title}
Source: {source_reference}
Team score: {score}% ({correct}/{total} decisions correct)

Team decisions:
{decisions_json}

NIST SP 800-61 control gaps identified:
{control_gaps}

Generate a structured debrief report as JSON inside <debrief> tags:

<debrief>
{{
  "executive_summary": "2-3 sentence summary for a CISO",
  "performance_rating": "excellent|good|needs_improvement|critical_gaps",
  "decisions": [
    {{
      "gate_id": "gate-001",
      "team_choice": "What the team chose",
      "correct_choice": "What they should have done",
      "is_correct": true/false,
      "impact": "What the consequence was",
      "nist_ref": "RS.CO-1",
      "explanation": "Why this matters"
    }}
  ],
  "nist_gaps": [
    {{
      "control": "RS.CO-2",
      "description": "Control description",
      "gap": "What the team failed to do",
      "remediation": "Specific action to close this gap"
    }}
  ],
  "mitre_coverage": {{
    "techniques_exercised": ["T1566", "T1078"],
    "techniques_missed": ["T1485"]
  }},
  "remediation_checklist": [
    {{
      "priority": "high|medium|low",
      "action": "Specific action item",
      "owner": "Suggested role (Incident Commander, SOC Lead, etc.)",
      "due_days": 30
    }}
  ],
  "compliance_evidence": {{
    "frameworks_exercised": ["HIPAA", "NIST IR"],
    "training_completed": true,
    "audit_notes": "This simulation satisfies IR tabletop exercise requirements under..."
  }}
}}
</debrief>"""


# ── Internal Claude callers (with retry) ──────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), before=_before_claude_retry, retry=retry_if_exception(_is_retryable_claude_error))
def _extract_via_claude(prompt_text: str, _is_retry_attempt: bool = False) -> str:
    start_time = time.perf_counter()
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt_text}],
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Claude extraction completed",
        extra={"model": settings.CLAUDE_MODEL, "elapsed_ms": elapsed_ms, "retry": _is_retry_attempt},
    )
    return message.content[0].text


# ── Nemotron structured-output schema ─────────────────────────────────────────
# Confirmed live against NVIDIA's endpoint (build.nvidia.com's OpenAI-compat
# API): response_format={"type":"json_schema", ..., "strict": True} is
# supported and, combined with the text instructions below, produces output
# that actually matches EXTRACTION_PROMPT's field names — the unconstrained
# path (no response_format) drifted to different top-level keys entirely
# (e.g. "scenario_title"/"decision_gates") and omitted "matches_on" from
# every hidden_ioc. This fixes STRUCTURE, not PROVENANCE — see the
# candidate-generation-only warning above; schema conformance says nothing
# about whether a given identifier is real.
#
# matches_on is modeled as all four keys present with three null rather than
# "exactly one of four possible keys", since strict mode requires every
# declared property to appear in `required` — there is no clean way to
# express "exactly one of N optional keys" without restructuring the actual
# data shape callers depend on downstream.
_NEMOTRON_MATCHES_ON_SCHEMA = {
    "type": "object",
    "properties": {
        "ip": {"type": ["string", "null"]},
        "hostname": {"type": ["string", "null"]},
        "username": {"type": ["string", "null"]},
        "process_name": {"type": ["string", "null"]},
    },
    "required": ["ip", "hostname", "username", "process_name"],
    "additionalProperties": False,
}
# Enterprise ATT&CK only (T1### / T1###.###) — deliberately excludes ATT&CK
# for ICS (T0###) even though source documents for ICS incidents often cite
# ICS IDs natively; this is OUR schema's choice for cross-scenario
# consistency, not a claim that ICS IDs are wrong for an ICS-native source.
_NEMOTRON_MITRE_SCHEMA = {"type": "string", "pattern": r"^T1[0-9]{3}(\.[0-9]{3})?$"}
_NEMOTRON_ALERT_SCHEMA = {
    "type": "object",
    "properties": {
        "timestamp": {"type": "string"},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "source_system": {"type": "string"},
        "rule_id": {"type": "string"},
        "description": {"type": "string"},
        "raw_log": {"type": "string"},
    },
    "required": ["timestamp", "severity", "source_system", "rule_id", "description", "raw_log"],
    "additionalProperties": False,
}
_NEMOTRON_HIDDEN_IOC_SCHEMA = {
    "type": "object",
    "properties": {
        "matches_on": _NEMOTRON_MATCHES_ON_SCHEMA,
        "timestamp": {"type": "string"},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "source_system": {"type": "string"},
        "rule_id": {"type": "string"},
        "description": {"type": "string"},
        "raw_log": {"type": "string"},
        "mitre_technique": _NEMOTRON_MITRE_SCHEMA,
    },
    "required": ["matches_on", "timestamp", "severity", "source_system", "rule_id", "description", "raw_log", "mitre_technique"],
    "additionalProperties": False,
}
_NEMOTRON_PRESSURE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "trigger_timestamp": {"type": "string"},
        "type": {"type": "string", "enum": ["email", "call", "news", "sms", "slack"]},
        "from": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "countdown_seconds": {"type": "integer"},
    },
    "required": ["id", "trigger_timestamp", "type", "from", "subject", "body", "countdown_seconds"],
    "additionalProperties": False,
}
_NEMOTRON_OPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "consequence_if_chosen": {"type": "string"},
    },
    "required": ["text", "consequence_if_chosen"],
    "additionalProperties": False,
}
_NEMOTRON_GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "trigger_timestamp": {"type": "string"},
        "countdown_seconds": {"type": "integer"},
        "urgency_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "gate_difficulty": {"type": "string", "enum": ["awareness", "practitioner", "expert", "critical"]},
        "context_summary": {"type": "string"},
        "options": {"type": "array", "items": _NEMOTRON_OPTION_SCHEMA, "minItems": 2, "maxItems": 6},
        "correct_index": {"type": "integer"},
        "consequence_if_wrong": {"type": "string"},
        "consequence_if_correct": {"type": "string"},
        "rationale": {"type": "string"},
        "nist_control_ref": {"type": "string"},
        "mitre_technique": _NEMOTRON_MITRE_SCHEMA,
    },
    "required": ["id", "trigger_timestamp", "countdown_seconds", "urgency_level", "gate_difficulty",
                 "context_summary", "options", "correct_index", "consequence_if_wrong",
                 "consequence_if_correct", "rationale", "nist_control_ref", "mitre_technique"],
    "additionalProperties": False,
}
_NEMOTRON_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "incident_date": {"type": ["string", "null"]},
        "incident_duration_hours": {"type": ["number", "null"]},
        "initial_access_vector": {"type": "string", "enum": ["phishing", "credential_theft", "unpatched_cve", "supply_chain", "insider_threat", "social_engineering", "physical", "unknown"]},
        "industry_vertical": {"type": "string", "enum": ["healthcare", "energy", "finance", "government", "technology", "retail", "education", "other"]},
        "difficulty": {"type": "string", "enum": ["awareness", "practitioner", "expert"]},
        "affected_asset_types": {"type": "array", "items": {"type": "string"}},
        "mitre_techniques": {"type": "array", "items": _NEMOTRON_MITRE_SCHEMA},
        "nist_controls": {"type": "array", "items": {"type": "string"}},
        "regulatory_frameworks": {"type": "array", "items": {"type": "string"}},
        "extraction_confidence": {"type": "number"},
        "alert_sequence": {"type": "array", "items": _NEMOTRON_ALERT_SCHEMA, "minItems": 20},
        "hidden_iocs": {"type": "array", "items": _NEMOTRON_HIDDEN_IOC_SCHEMA, "minItems": 4},
        "pressure_injections": {"type": "array", "items": _NEMOTRON_PRESSURE_SCHEMA, "minItems": 6},
        "decision_tree": {"type": "array", "items": _NEMOTRON_GATE_SCHEMA, "minItems": 12},
    },
    "required": ["title", "incident_date", "incident_duration_hours", "initial_access_vector",
                 "industry_vertical", "difficulty", "affected_asset_types", "mitre_techniques",
                 "nist_controls", "regulatory_frameworks", "extraction_confidence",
                 "alert_sequence", "hidden_iocs", "pressure_injections", "decision_tree"],
    "additionalProperties": False,
}
_NEMOTRON_SCHEMA_ENFORCEMENT_SUFFIX = """

STRICT OUTPUT CONTRACT — this is enforced by a JSON schema, but follow it explicitly too:
- Use EXACTLY these field names, no synonyms: "title" (not scenario_title), "decision_tree" (not decision_gates),
  "context_summary" + "options"/"consequence_if_chosen" (not question_text), "hidden_iocs" with "matches_on"/
  "severity"/"timestamp"/"source_system"/"rule_id"/"description"/"raw_log"/"mitre_technique" on every entry.
- "matches_on" must have all four keys (ip, hostname, username, process_name) present, with exactly one set to
  the real string value and the other three set to null.
- ALL mitre_technique values must be ENTERPRISE ATT&CK technique IDs in the form T1### or T1###.###
  (e.g. T1078, T1003, T1547.001) — NEVER ATT&CK for ICS IDs (never T0### under any circumstance).
- Include "pressure_injections" — do not omit it.
"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception(_is_retryable_nemotron_error))
def _extract_via_nemotron(prompt_text: str) -> str:
    """Streams the response so reasoning_content (the model's chain-of-thought,
    emitted separately from content when thinking is enabled) can be dropped
    chunk-by-chunk rather than ever landing in the string that
    _extract_tagged_json parses — a reasoning trace mixed into the JSON
    payload would break parsing or silently leak into extraction_confidence-
    adjacent fields. response_format enforces the same field-name contract
    Claude's path follows by prompt convention alone — see
    docs/NEMOTRON_EXTRACTION_FINDINGS.md for why this was needed and what it
    does/doesn't fix (structure, not provenance)."""
    if _nvidia_client is None:
        raise RuntimeError("Nemotron extraction requested but NVIDIA_API_KEY is not configured")

    start_time = time.perf_counter()
    stream = _nvidia_client.chat.completions.create(
        model=settings.NVIDIA_MODEL,
        messages=[{"role": "user", "content": prompt_text + _NEMOTRON_SCHEMA_ENFORCEMENT_SUFFIX}],
        # Reasoning tokens (reasoning_content) count against the same
        # max_tokens budget as the final content on this endpoint — confirmed
        # live: an 8192 cap (matched to Claude's, which has no such shared
        # budget) let "thinking" consume the entire ceiling and return
        # finish_reason="length" with zero content before ever reaching the
        # extraction JSON. This extraction prompt's reasoning alone routinely
        # runs 25-50k+ chars, so the ceiling needs real headroom.
        max_tokens=32768,
        stream=True,
        response_format={"type": "json_schema", "json_schema": {"name": "breach_extraction", "schema": _NEMOTRON_EXTRACTION_SCHEMA, "strict": True}},
        extra_body={"chat_template_kwargs": {"thinking": True}},
    )
    content_parts: list[str] = []
    reasoning_chars = 0
    finish_reason = None
    for chunk in stream:
        delta = chunk.choices[0].delta
        reasoning_piece = getattr(delta, "reasoning_content", None)
        if reasoning_piece:
            reasoning_chars += len(reasoning_piece)
            continue
        content_piece = getattr(delta, "content", None)
        if content_piece:
            content_parts.append(content_piece)
        if chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Nemotron extraction completed",
        extra={
            "model": settings.NVIDIA_MODEL,
            "elapsed_ms": elapsed_ms,
            "reasoning_chars_discarded": reasoning_chars,
            "finish_reason": finish_reason,
        },
    )
    if finish_reason == "length" and not content_parts:
        # Thinking consumed the entire max_tokens budget before any content
        # was emitted — a silent empty-string return here would fail JSON
        # parsing downstream with a confusing "Expecting value" error that
        # gives no hint why. Raise with the real cause instead.
        raise RuntimeError(
            f"Nemotron hit max_tokens during reasoning ({reasoning_chars} reasoning chars) "
            "before emitting any content — raise max_tokens further."
        )
    return "".join(content_parts)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), before=_before_claude_retry, retry=retry_if_exception(_is_retryable_claude_error))
def _debrief_via_claude(prompt_text: str, _is_retry_attempt: bool = False) -> str:
    start_time = time.perf_counter()
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt_text}],
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Claude debrief completed",
        extra={"model": settings.CLAUDE_MODEL, "elapsed_ms": elapsed_ms, "retry": _is_retry_attempt},
    )
    return message.content[0].text


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_scenario_from_document(document_text: str) -> dict:
    safe_text = _sanitize_document(document_text)
    prompt_text = EXTRACTION_PROMPT.format(document_text=safe_text)

    if settings.EXTRACTION_PROVIDER == "nemotron":
        # No Claude/Gemini fallback by design — a failed Nemotron extraction
        # should surface as a failure so it's obvious which provider produced
        # (or failed to produce) a given scenario, not silently substitute a
        # different model's output under the same "nemotron" label.
        raw = _extract_via_nemotron(prompt_text)
        logger.info("Scenario extraction used provider=nemotron")
        return _extract_tagged_json(raw, "extracted")

    if settings.AI_PREFER_GEMINI and _gemini_model is not None:
        try:
            raw = _call_gemini(prompt_text, _gemini_model, max_tokens=8192)
            logger.info("Scenario extraction used provider=gemini (preferred)")
        except Exception as exc:
            logger.warning("Gemini extraction failed (%s), falling back to Claude", type(exc).__name__)
            raw = _extract_via_claude(prompt_text)
            logger.info("Scenario extraction used provider=claude (fallback)")
    else:
        try:
            raw = _extract_via_claude(prompt_text)
            logger.info("Scenario extraction used provider=claude")
        except Exception as exc:
            if _gemini_model is not None:
                logger.warning("Claude unavailable (%s), falling back to Gemini", type(exc).__name__)
                raw = _call_gemini(prompt_text, _gemini_model, max_tokens=8192)
                logger.info("Scenario extraction used provider=gemini")
            else:
                raise

    return _extract_tagged_json(raw, "extracted")


def generate_decision_commentary(
    scenario_title: str,
    gate_id: str,
    team_choice: str,
    correct_choice: str,
    is_correct: bool,
    mitre_technique: str,
    nist_ref: str,
) -> str:
    """
    2-3 sentence live facilitator commentary delivered via WebSocket after each gate.
    Fast/low-token call — uses Haiku (or Gemini Flash as fallback).
    """
    verdict = "correct" if is_correct else "incorrect"
    prompt = (
        f"You are a live cybersecurity incident response facilitator narrating a tabletop simulation of '{scenario_title}'.\n"
        f"The team just made a {verdict} decision at checkpoint {gate_id}.\n"
        f"Team chose: {team_choice}\n"
        f"Best action: {correct_choice}\n"
        f"MITRE: {mitre_technique or 'N/A'} | NIST: {nist_ref or 'N/A'}\n\n"
        f"Write EXACTLY 2 sentences of live facilitator commentary: (1) connect this to what happened in the real-world incident or attacker TTPs, "
        f"(2) name the specific MITRE technique or NIST control at play and its operational significance. "
        f"Be specific, urgent, and educational. No preamble. Just the 2 sentences."
    )
    if settings.AI_PREFER_GEMINI and _gemini_flash is not None:
        try:
            result = _call_gemini(prompt, _gemini_flash, max_tokens=180).strip()
            logger.info("Decision commentary used provider=gemini-flash (preferred)")
            return result
        except Exception as exc:
            logger.warning("Gemini Flash commentary failed (%s), falling back to Claude Haiku", type(exc).__name__)
            try:
                message = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=180,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text.strip()
            except Exception as haiku_exc:
                logger.warning("Claude Haiku commentary fallback also failed: %s", haiku_exc)
                return ""
    else:
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=180,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            if _gemini_flash is not None:
                logger.warning("Claude Haiku unavailable (%s), falling back to Gemini Flash for commentary", type(exc).__name__)
                try:
                    return _call_gemini(prompt, _gemini_flash, max_tokens=180).strip()
                except Exception as gemini_exc:
                    logger.warning("Gemini Flash commentary failed: %s", gemini_exc)
            else:
                logger.warning("AI commentary generation failed: %s", exc)
            return ""


def generate_debrief_report(
    scenario_title: str,
    source_reference: str,
    score: float,
    correct: int,
    total: int,
    decisions: list,
    control_gaps: list,
) -> dict:
    safe_title = _sanitize_document(scenario_title)
    safe_ref = _sanitize_document(source_reference or "N/A")

    prompt_text = DEBRIEF_PROMPT.format(
        scenario_title=safe_title,
        source_reference=safe_ref,
        score=score,
        correct=correct,
        total=total,
        decisions_json=json.dumps(decisions, indent=2),
        control_gaps=json.dumps(control_gaps, indent=2),
    )

    if settings.AI_PREFER_GEMINI and _gemini_model is not None:
        try:
            raw = _call_gemini(prompt_text, _gemini_model, max_tokens=8192)
            logger.info("Debrief report used provider=gemini (preferred)")
        except Exception as exc:
            logger.warning("Gemini debrief failed (%s), falling back to Claude", type(exc).__name__)
            raw = _debrief_via_claude(prompt_text)
            logger.info("Debrief report used provider=claude (fallback)")
    else:
        try:
            raw = _debrief_via_claude(prompt_text)
            logger.info("Debrief report used provider=claude")
        except Exception as exc:
            if _gemini_model is not None:
                logger.warning("Claude unavailable (%s), falling back to Gemini for debrief", type(exc).__name__)
                raw = _call_gemini(prompt_text, _gemini_model, max_tokens=8192)
                logger.info("Debrief report used provider=gemini")
            else:
                raise

    return _extract_tagged_json(raw, "debrief")
