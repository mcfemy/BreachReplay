"""
Tests for the document-extraction pipeline's hidden_iocs support
(backend/app/pipeline/claude_client.py's EXTRACTION_PROMPT schema,
backend/app/pipeline/tasks.py's _validate_extracted + scenario_data
persistence).

Root cause this closes: EXTRACTION_PROMPT never asked for hidden_iocs, so
no document ingestion has ever produced them — the field exists in both
consumers' contracts (main's simulation_ws_handler._match_hidden_iocs
investigation-panel pivot, and Phase 2's action_engine._place_iocs verb
discovery) but nothing has ever populated it. This file covers the two
testable halves: _validate_extracted's new hidden_iocs validation (a pure
function, no LLM/DB involved), and the full process_advisory_url pipeline
carrying a mocked extraction's hidden_iocs through to the persisted
Scenario row (no real Claude/Gemini call — extract_scenario_from_document
itself is a thin API wrapper with no branching logic of its own worth
testing against a live model).
"""
import uuid

from app.pipeline.tasks import _validate_extracted, process_advisory_url


def _valid_ioc(**overrides) -> dict:
    base = {
        "matches_on": {"ip": "185.220.101.34"},
        "rule_id": "AUTH-009",
        "description": "test finding",
        "source_system": "Auth",
        "raw_log": "event=4624 src_ip=185.220.101.34",
    }
    base.update(overrides)
    return base


# ── _validate_extracted ───────────────────────────────────────────────────────

def test_validate_extracted_keeps_well_formed_hidden_iocs():
    extracted = {"hidden_iocs": [_valid_ioc(), _valid_ioc(rule_id="AUTH-010")]}
    result = _validate_extracted(extracted)
    assert len(result["hidden_iocs"]) == 2


def test_validate_extracted_drops_hidden_iocs_missing_a_required_field():
    missing_raw_log = _valid_ioc()
    del missing_raw_log["raw_log"]
    extracted = {"hidden_iocs": [_valid_ioc(), missing_raw_log]}
    result = _validate_extracted(extracted)
    assert len(result["hidden_iocs"]) == 1


def test_validate_extracted_drops_hidden_iocs_with_no_matches_on():
    """matches_on is the pivot key both consumers (main's investigation
    panel, Phase 2's block_ip/query_logs discovery) key off of — an entry
    without one is unreachable through legitimate play on either path, so
    it must be dropped just like a missing required field, not silently
    kept with an empty dict."""
    no_pivot = _valid_ioc(matches_on={})
    extracted = {"hidden_iocs": [_valid_ioc(), no_pivot]}
    result = _validate_extracted(extracted)
    assert len(result["hidden_iocs"]) == 1


def test_validate_extracted_handles_missing_hidden_iocs_key():
    """Claude output that predates this fix (or a low-confidence
    extraction that omitted the field) must not crash — defaults to []
    same as the other three list fields already do."""
    result = _validate_extracted({"title": "no hidden_iocs key at all"})
    assert result["hidden_iocs"] == []


# ── Full pipeline: extraction -> validation -> persisted Scenario row ────────

def test_process_advisory_url_persists_hidden_iocs_end_to_end(monkeypatch):
    """The actual bug: hidden_iocs existed in Claude's response shape
    nowhere — this proves that once extract_scenario_from_document DOES
    return them (mocked here as the fixed prompt would produce), they
    survive validation and land on the persisted Scenario row exactly as
    given. No real Claude/Gemini call — extract_scenario_from_document
    itself has no logic of its own worth exercising against a live model
    here; the prompt content change is covered by reading
    EXTRACTION_PROMPT directly (see test below)."""
    source_ref = f"TEST-HIDDEN-IOC-{uuid.uuid4().hex[:8]}"
    fixture_iocs = [_valid_ioc(rule_id="EDR-030", description="LOLBin activity on the domain controller")]

    def fake_extract(document_text: str) -> dict:
        return {
            "title": "Hidden IOC Pipeline Test Scenario",
            "extraction_confidence": 0.9,
            "alert_sequence": [],
            "decision_tree": [],
            "pressure_injections": [],
            "hidden_iocs": fixture_iocs,
        }

    monkeypatch.setattr("app.pipeline.tasks.extract_scenario_from_document", fake_extract)
    monkeypatch.setattr("app.pipeline.tasks.fetch_plain_text", lambda url: "x" * 300)
    monkeypatch.setattr("app.pipeline.tasks.is_source_already_processed", lambda ref: False)

    from app.db.session import SyncSessionLocal
    from app.models.scenario import Scenario
    from sqlalchemy import select

    try:
        result = process_advisory_url(
            url="http://fake.test/doc", source_type="manual", source_reference=source_ref,
        )
        assert result["status"] == "success"

        with SyncSessionLocal() as db:
            scenario = db.execute(
                select(Scenario).where(Scenario.source_reference == source_ref)
            ).scalar_one_or_none()
            assert scenario is not None
            assert scenario.hidden_iocs == fixture_iocs
    finally:
        with SyncSessionLocal() as db:
            leftover = db.execute(
                select(Scenario).where(Scenario.source_reference == source_ref)
            ).scalar_one_or_none()
            if leftover is not None:
                db.delete(leftover)
                db.commit()


# ── Prompt schema ──────────────────────────────────────────────────────────────

def test_extraction_prompt_asks_for_hidden_iocs():
    """Direct regression guard for the actual root cause: the prompt text
    itself must mention hidden_iocs and its pivot mechanism, not just the
    downstream plumbing. Would have failed before this fix — the prompt
    had no hidden_iocs field at all."""
    from app.pipeline.claude_client import EXTRACTION_PROMPT

    assert "hidden_iocs" in EXTRACTION_PROMPT
    assert "matches_on" in EXTRACTION_PROMPT
