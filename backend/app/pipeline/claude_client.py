import re
import time
import anthropic
import json
from app.core.config import settings
from app.core.logging import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential, RetryCallState, retry_if_exception

# ── Gemini fallback setup ──────────────────────────────────────────────────────
try:
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

    try:
        raw = _extract_via_claude(prompt_text)
        logger.info("Scenario extraction used provider=claude")
    except Exception as exc:
        if _gemini_model is not None:
            logger.warning("Claude unavailable (%s), falling back to Gemini for extraction", type(exc).__name__)
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
