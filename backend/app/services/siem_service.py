"""SIEM webhook dispatcher — formats and delivers events to customer SIEM."""
import base64
import datetime
import hashlib
import hmac
import json
import time
from typing import Optional

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = 5.0  # seconds — don't block simulation on slow SIEMs


def format_alert_for_siem(alert: dict, scenario_title: str, fmt: str) -> "dict | list":
    """Format a simulation alert dict into the target SIEM wire format."""
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    if fmt == "splunk_hec":
        return {
            "time": time.time(),
            "source": "breachreplay",
            "sourcetype": "ir_simulation",
            "event": {
                "alert": alert,
                "scenario": scenario_title,
                "severity": alert.get("severity", ""),
                "source_system": alert.get("source_system", ""),
                "description": alert.get("description", ""),
                "raw_log": alert.get("raw_log", ""),
            },
        }

    if fmt == "sentinel":
        return [
            {
                "TimeGenerated": now_iso,
                "Source": "BreachReplay",
                "ScenarioTitle": scenario_title,
                "Severity": alert.get("severity", ""),
                "SourceSystem": alert.get("source_system", ""),
                "Description": alert.get("description", ""),
                "RawLog": alert.get("raw_log", ""),
                "Type": "BreachReplayAlert",
            }
        ]

    # generic (default)
    return {
        "source": "breachreplay",
        "event_type": "simulation_alert",
        "timestamp": now_iso,
        "scenario": scenario_title,
        "data": alert,
    }


def format_decision_for_siem(decision: dict, scenario_title: str, fmt: str) -> "dict | list":
    """Format a gate decision dict into the target SIEM wire format."""
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    base_event = {
        "gate_id": decision.get("gate_id", ""),
        "chosen_option": decision.get("chosen_option_text", ""),
        "is_correct": decision.get("is_correct", False),
        "score_impact": decision.get("score_impact", 0),
        "scenario": scenario_title,
    }

    if fmt == "splunk_hec":
        return {
            "time": time.time(),
            "source": "breachreplay",
            "sourcetype": "ir_simulation",
            "event": {**base_event, "event_type": "gate_decision"},
        }

    if fmt == "sentinel":
        return [
            {
                "TimeGenerated": now_iso,
                "Source": "BreachReplay",
                "Type": "BreachReplayDecision",
                **base_event,
            }
        ]

    # generic
    return {
        "source": "breachreplay",
        "event_type": "gate_decision",
        "timestamp": now_iso,
        **base_event,
    }


def compute_sentinel_auth(
    workspace_id: str,
    shared_key: str,
    content_length: int,
    date_str: str,
) -> str:
    """Compute Azure Monitor / Sentinel HMAC-SHA256 authorization header."""
    string_to_sign = (
        f"POST\n{content_length}\napplication/json\nx-ms-date:{date_str}\n/api/logs"
    )
    decoded_key = base64.b64decode(shared_key)
    signature = base64.b64encode(
        hmac.new(decoded_key, string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode()
    return f"SharedKey {workspace_id}:{signature}"


async def fire_webhook(config: dict, payload: "dict | list", fmt: str) -> dict:
    """
    POST payload to the configured webhook URL.

    Returns:
        {"success": bool, "status_code": int|None, "latency_ms": float, "error": str|None}
    """
    body = json.dumps(payload)
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if fmt == "splunk_hec":
        token = config.get("auth_token", "")
        if token:
            headers["Authorization"] = f"Splunk {token}"

    elif fmt == "sentinel":
        date_str = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
        workspace_id = config.get("sentinel_workspace_id", "")
        shared_key = config.get("sentinel_shared_key", "")
        if workspace_id and shared_key:
            auth_header = compute_sentinel_auth(
                workspace_id, shared_key, len(body.encode("utf-8")), date_str
            )
            headers["Authorization"] = auth_header
            headers["x-ms-date"] = date_str
            headers["Log-Type"] = "BreachReplayAlerts"

    else:  # generic
        token = config.get("auth_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(config["webhook_url"], content=body, headers=headers)
        latency_ms = (time.monotonic() - start) * 1000
        success = 200 <= response.status_code < 300
        return {
            "success": success,
            "status_code": response.status_code,
            "latency_ms": round(latency_ms, 2),
            "error": None if success else f"HTTP {response.status_code}: {response.text[:200]}",
        }
    except httpx.TimeoutException as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "success": False,
            "status_code": None,
            "latency_ms": round(latency_ms, 2),
            "error": f"Timeout after {TIMEOUT}s: {exc}",
        }
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "success": False,
            "status_code": None,
            "latency_ms": round(latency_ms, 2),
            "error": str(exc),
        }


async def send_alert_to_siem(org_id: str, alert: dict, scenario_title: str) -> None:
    """
    Fire-and-forget: load org's SIEM config from Redis and dispatch an alert.
    Never raises — safe to call from asyncio.create_task().
    """
    try:
        from app.core.redis import get_redis  # local import avoids circular deps

        redis = await get_redis()
        raw = await redis.get(f"siem:{org_id}")
        if not raw:
            return

        config = json.loads(raw)
        if not config.get("enabled", True):
            return
        if not config.get("send_alerts", True):
            return

        fmt = config.get("format", "generic")
        payload = format_alert_for_siem(alert, scenario_title, fmt)
        result = await fire_webhook(config, payload, fmt)
        if result["success"]:
            logger.info(
                "SIEM alert dispatched",
                extra={"org_id": org_id, "format": fmt, "latency_ms": result["latency_ms"]},
            )
        else:
            logger.warning(
                "SIEM alert dispatch failed",
                extra={"org_id": org_id, "format": fmt, "error": result["error"]},
            )
    except Exception:
        logger.exception("Unexpected error in send_alert_to_siem for org %s", org_id)


async def send_decision_to_siem(org_id: str, decision: dict, scenario_title: str) -> None:
    """
    Fire-and-forget: load org's SIEM config from Redis and dispatch a gate decision.
    Never raises — safe to call from asyncio.create_task().
    """
    try:
        from app.core.redis import get_redis  # local import avoids circular deps

        redis = await get_redis()
        raw = await redis.get(f"siem:{org_id}")
        if not raw:
            return

        config = json.loads(raw)
        if not config.get("enabled", True):
            return
        if not config.get("send_decisions", True):
            return

        fmt = config.get("format", "generic")
        payload = format_decision_for_siem(decision, scenario_title, fmt)
        result = await fire_webhook(config, payload, fmt)
        if result["success"]:
            logger.info(
                "SIEM decision dispatched",
                extra={"org_id": org_id, "format": fmt, "latency_ms": result["latency_ms"]},
            )
        else:
            logger.warning(
                "SIEM decision dispatch failed",
                extra={"org_id": org_id, "format": fmt, "error": result["error"]},
            )
    except Exception:
        logger.exception("Unexpected error in send_decision_to_siem for org %s", org_id)
