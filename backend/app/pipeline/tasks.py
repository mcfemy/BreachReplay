import asyncio
import json
from datetime import datetime, timezone

import redis
import sentry_sdk
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.scenario import Scenario
from app.models.session import SimulationSession, SessionDecision
from app.pipeline.celery_app import celery_app
from app.pipeline.claude_client import extract_scenario_from_document, generate_debrief_report
from app.pipeline.ingestion import search_cisa_advisories, fetch_plain_text


logger = get_logger(__name__)
redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _store_task_failure(task_name: str, task_id: str, error: str) -> None:
    payload = {
        "task_name": task_name,
        "task_id": task_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.setex(f"task_failure:{task_name}:{task_id}", 86400, json.dumps(payload))


def _handle_task_failure(task, error: Exception) -> None:
    task_name = task.name
    task_id = task.request.id
    logger.exception(
        "Celery task failed",
        extra={
            "task_name": task_name,
            "task_id": task_id,
            "task_args": task.request.args,
            "task_kwargs": task.request.kwargs,
            "exception_type": type(error).__name__,
        },
    )
    if settings.SENTRY_DSN:
        sentry_sdk.capture_exception(error)
    try:
        _store_task_failure(task_name, task_id, str(error))
    except Exception:
        logger.exception("Failed to store Celery task failure", extra={"task_name": task_name, "task_id": task_id})


@celery_app.task(bind=True, name="app.pipeline.tasks.ingest_cisa_advisories")
def ingest_cisa_advisories(self, limit: int = 5):
    try:
        advisory_urls = search_cisa_advisories(limit=limit)
        results = []
        for url in advisory_urls:
            try:
                result = process_advisory_url.delay(url, source_type="cisa", source_reference=url.split("/")[-1])
                results.append({"url": url, "task_id": result.id})
            except Exception as e:
                results.append({"url": url, "error": str(e)})
        return results
    except Exception as e:
        _handle_task_failure(self, e)
        raise


@celery_app.task(bind=True, name="app.pipeline.tasks.process_advisory_url")
def process_advisory_url(self, url: str, source_type: str = "cisa", source_reference: str = None):
    try:
        text = fetch_plain_text(url)
        if not text or len(text) < 200:
            raise ValueError(f"Insufficient content from {url}")

        extracted = extract_scenario_from_document(text)

        if extracted.get("extraction_confidence", 0) < 0.4:
            return {"status": "rejected", "reason": "Low extraction confidence", "confidence": extracted.get("extraction_confidence")}

        scenario_data = {
            "title": extracted.get("title", "Untitled Scenario"),
            "source_type": source_type,
            "source_url": url,
            "source_reference": source_reference,
            "incident_date": extracted.get("incident_date"),
            "incident_duration_hours": extracted.get("incident_duration_hours"),
            "initial_access_vector": extracted.get("initial_access_vector"),
            "industry_vertical": extracted.get("industry_vertical"),
            "affected_asset_types": extracted.get("affected_asset_types"),
            "mitre_techniques": extracted.get("mitre_techniques"),
            "nist_controls": extracted.get("nist_controls"),
            "regulatory_frameworks": extracted.get("regulatory_frameworks"),
            "extraction_confidence": extracted.get("extraction_confidence"),
            "alert_sequence": extracted.get("alert_sequence"),
            "decision_tree": extracted.get("decision_tree"),
            "status": "review" if extracted.get("extraction_confidence", 0) >= 0.7 else "draft",
        }

        asyncio.run(_save_scenario(scenario_data))
        return {"status": "success", "title": scenario_data["title"], "confidence": extracted.get("extraction_confidence")}
    except Exception as e:
        _handle_task_failure(self, e)
        raise


@celery_app.task(bind=True, name="app.pipeline.tasks.generate_session_debrief")
def generate_session_debrief(self, session_id: str):
    try:
        asyncio.run(_generate_debrief(session_id))
    except Exception as e:
        _handle_task_failure(self, e)
        raise


async def _save_scenario(data: dict):
    async with AsyncSessionLocal() as db:
        scenario = Scenario(**{k: v for k, v in data.items() if v is not None})
        db.add(scenario)
        await db.commit()


async def _generate_debrief(session_id: str):
    async with AsyncSessionLocal() as db:
        s_result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
        session = s_result.scalar_one_or_none()
        if not session:
            return

        sc_result = await db.execute(select(Scenario).where(Scenario.id == session.scenario_id))
        scenario = sc_result.scalar_one_or_none()

        d_result = await db.execute(select(SessionDecision).where(SessionDecision.session_id == session_id))
        decisions_raw = d_result.scalars().all()

        decision_tree_map = {g["id"]: g for g in (scenario.decision_tree or [])}

        decisions = []
        control_gaps = []
        for d in decisions_raw:
            gate = decision_tree_map.get(d.decision_gate_id, {})
            options = gate.get("options", [])
            decisions.append({
                "gate_id": d.decision_gate_id,
                "team_choice": options[d.chosen_option_index]["text"] if d.chosen_option_index < len(options) else "Unknown",
                "correct_choice": options[gate.get("correct_index", 0)]["text"] if options else "Unknown",
                "is_correct": d.is_correct,
                "nist_ref": d.nist_control_ref,
                "mitre_technique": d.mitre_technique,
            })
            if not d.is_correct and d.nist_control_ref:
                control_gaps.append({"control": d.nist_control_ref, "gate_id": d.decision_gate_id})

        report = generate_debrief_report(
            scenario_title=scenario.title,
            source_reference=scenario.source_reference,
            score=session.team_score or 0,
            correct=session.decisions_correct,
            total=session.decisions_made,
            decisions=decisions,
            control_gaps=control_gaps,
        )

        session.debrief_report = report
        session.debrief_generated_at = datetime.utcnow()
        await db.commit()
