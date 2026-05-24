import re
import time
import anthropic
import json
from app.core.config import settings
from app.core.logging import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential, RetryCallState

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
logger = get_logger(__name__)


def _before_claude_retry(retry_state: RetryCallState) -> None:
    if retry_state.attempt_number > 1:
        retry_state.kwargs["_is_retry_attempt"] = True

# ── Prompt-injection sanitization ─────────────────────────────────────────────
# Maximum document size before the LLM call (~200 KB ≈ 50 K tokens at 4 chars/token)
_MAX_DOC_CHARS = 200_000

# Control characters except \t, \n, \r which are legitimate in documents
_CTRL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Tags used by our own prompt parsers — strip them from user input so an
# attacker cannot inject a fake <extracted> or <debrief> block.
_INJECTION_TAG_RE = re.compile(
    r'</?(?:extracted|debrief|document|system|human|assistant)\b[^>]*>',
    re.IGNORECASE,
)


def _sanitize_document(text: str) -> str:
    """Strip control chars, injection tags, and enforce max length."""
    text = _CTRL_CHAR_RE.sub('', text)
    text = _INJECTION_TAG_RE.sub('', text)
    if len(text) > _MAX_DOC_CHARS:
        text = text[:_MAX_DOC_CHARS]
    return text


EXTRACTION_PROMPT = """You are a cybersecurity incident analyst. I will provide you with a breach disclosure document.

Extract the following information and return it as structured JSON inside <extracted> tags.

<document>
{document_text}
</document>

Return JSON with this exact schema:
<extracted>
{{
  "title": "Short descriptive title of the incident",
  "incident_date": "YYYY-MM-DD or null",
  "incident_duration_hours": number or null,
  "initial_access_vector": "e.g. phishing, credential_theft, unpatched_cve, supply_chain, etc.",
  "industry_vertical": "healthcare|energy|finance|government|technology|retail|education|other",
  "affected_asset_types": ["list", "of", "asset", "types"],
  "mitre_techniques": ["T1566", "T1078", ...],
  "nist_controls": ["DE.AE-1", "RS.CO-2", ...],
  "regulatory_frameworks": ["HIPAA", "CMMC", ...],
  "extraction_confidence": 0.0 to 1.0,
  "chronological_timeline": [
    {{"timestamp_offset_minutes": 0, "event": "description of what happened"}}
  ],
  "alert_sequence": [
    {{
      "timestamp": "+0m",
      "severity": "critical|high|medium|low",
      "source_system": "SIEM|EDR|Firewall|Auth|Network",
      "rule_id": "RULE-001",
      "description": "Alert description as it would appear in a real SIEM",
      "raw_log": "Simulated raw log line"
    }}
  ],
  "decision_tree": [
    {{
      "id": "gate-001",
      "trigger_timestamp": "+15m",
      "context_summary": "What is happening right now and what the analyst needs to decide",
      "options": [
        {{"text": "Option A action", "consequence_if_chosen": "What happens if you pick this"}},
        {{"text": "Option B action", "consequence_if_chosen": "What happens if you pick this"}},
        {{"text": "Option C action", "consequence_if_chosen": "What happens if you pick this"}}
      ],
      "correct_index": 0,
      "consequence_if_wrong": "Specific downstream consequence that makes the scenario harder",
      "rationale": "Why this is the correct NIST IR action and what the real team did",
      "nist_control_ref": "RS.CO-1",
      "mitre_technique": "T1078"
    }}
  ]
}}
</extracted>

Be precise. If information is not available in the document, use null. Do not invent details not supported by the source."""


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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), before=_before_claude_retry)
def extract_scenario_from_document(document_text: str, _is_retry_attempt: bool = False) -> dict:
    safe_text = _sanitize_document(document_text)
    prompt_text = EXTRACTION_PROMPT.format(document_text=safe_text)
    start_time = time.perf_counter()
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt_text}],
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Claude message create completed",
        extra={
            "model": settings.CLAUDE_MODEL,
            "estimated_prompt_tokens": len(prompt_text) // 4,
            "elapsed_ms": elapsed_ms,
            "retry_attempt": _is_retry_attempt,
        },
    )
    raw = message.content[0].text
    open_pos = raw.find("<extracted>")
    end = raw.find("</extracted>")
    if open_pos == -1 or end == -1:
        raise ValueError("Could not find <extracted> tags in Claude response")
    return json.loads(raw[open_pos + len("<extracted>"):end].strip())


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), before=_before_claude_retry)
def generate_debrief_report(
    scenario_title: str,
    source_reference: str,
    score: float,
    correct: int,
    total: int,
    decisions: list,
    control_gaps: list,
    _is_retry_attempt: bool = False,
) -> dict:
    # Sanitize any user-influenced strings before insertion into the prompt
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
    start_time = time.perf_counter()
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": prompt_text,
        }],
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Claude message create completed",
        extra={
            "model": settings.CLAUDE_MODEL,
            "estimated_prompt_tokens": len(prompt_text) // 4,
            "elapsed_ms": elapsed_ms,
            "retry_attempt": _is_retry_attempt,
        },
    )
    raw = message.content[0].text
    open_pos = raw.find("<debrief>")
    end = raw.find("</debrief>")
    if open_pos == -1 or end == -1:
        raise ValueError("Could not find <debrief> tags in Claude response")
    return json.loads(raw[open_pos + len("<debrief>"):end].strip())
