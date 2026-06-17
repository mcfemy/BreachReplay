"""SIEM Webhook Integration — stream simulation alerts to customer SIEM."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.siem_service import fire_webhook, format_alert_for_siem

router = APIRouter(prefix="/siem", tags=["siem"])
logger = get_logger(__name__)

SIEM_TTL = 365 * 24 * 3600  # 365 days

SUPPORTED_FORMATS: dict = {
    "splunk_hec": {
        "name": "Splunk HTTP Event Collector (HEC)",
        "description": "Streams events to Splunk Enterprise or Splunk Cloud via HEC token auth",
        "auth_header": "Authorization: Splunk {token}",
        "payload_example": {
            "time": 1234567890,
            "source": "breachreplay",
            "event": {"alert": "...", "scenario": "...", "severity": "high"},
        },
    },
    "sentinel": {
        "name": "Microsoft Sentinel / Log Analytics Workspace",
        "description": "Sends events to Azure Monitor via Workspace ID + Shared Key",
        "auth_header": "Custom HMAC signature (handled automatically)",
        "payload_example": [
            {
                "TimeGenerated": "2025-01-01T00:00:00Z",
                "Source": "BreachReplay",
                "Alert": "...",
            }
        ],
    },
    "generic": {
        "name": "Generic Webhook (JSON POST)",
        "description": (
            "Plain JSON POST to any webhook receiver "
            "(Elastic SIEM, QRadar, custom endpoints)"
        ),
        "auth_header": "Authorization: Bearer {token}",
        "payload_example": {
            "source": "breachreplay",
            "event_type": "alert",
            "data": {"alert": "..."},
        },
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SIEMConfig(BaseModel):
    format: str  # splunk_hec | sentinel | generic
    webhook_url: str  # plain str — easier validation than HttpUrl for enterprise URLs
    auth_token: Optional[str] = None  # HEC token / Bearer token
    sentinel_workspace_id: Optional[str] = None
    sentinel_shared_key: Optional[str] = None
    enabled: bool = True
    send_alerts: bool = True
    send_decisions: bool = True
    send_debrief: bool = False


class SIEMConfigOut(BaseModel):
    format: str
    webhook_url: str
    enabled: bool
    send_alerts: bool
    send_decisions: bool
    send_debrief: bool
    # auth_token and sentinel keys are intentionally excluded


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _scope_id(user: User) -> str:
    """Return the Redis key scope: org_id if present, else user.id."""
    return user.organization_id if user.organization_id else user.id


def _redis_key(scope: str) -> str:
    return f"siem:{scope}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/configure", response_model=SIEMConfigOut, status_code=status.HTTP_200_OK)
async def configure_siem(
    body: SIEMConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save or update the org's SIEM webhook configuration."""
    if body.format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported format '{body.format}'. Supported: {list(SUPPORTED_FORMATS)}",
        )

    if not body.webhook_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="webhook_url must start with http:// or https://",
        )

    scope = _scope_id(current_user)
    redis = await get_redis()

    config_data = body.model_dump()
    await redis.set(_redis_key(scope), json.dumps(config_data), ex=SIEM_TTL)

    logger.info("SIEM config saved", extra={"scope": scope, "format": body.format})

    return SIEMConfigOut(
        format=body.format,
        webhook_url=body.webhook_url,
        enabled=body.enabled,
        send_alerts=body.send_alerts,
        send_decisions=body.send_decisions,
        send_debrief=body.send_debrief,
    )


@router.get("/config", response_model=SIEMConfigOut)
async def get_siem_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the current SIEM webhook configuration (secrets stripped)."""
    scope = _scope_id(current_user)
    redis = await get_redis()
    raw = await redis.get(_redis_key(scope))

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SIEM configuration found. Use POST /siem/configure to set one up.",
        )

    config = json.loads(raw)
    return SIEMConfigOut(
        format=config["format"],
        webhook_url=config["webhook_url"],
        enabled=config.get("enabled", True),
        send_alerts=config.get("send_alerts", True),
        send_decisions=config.get("send_decisions", True),
        send_debrief=config.get("send_debrief", False),
    )


@router.delete("/config", status_code=status.HTTP_200_OK)
async def delete_siem_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the SIEM webhook configuration."""
    scope = _scope_id(current_user)
    redis = await get_redis()
    deleted = await redis.delete(_redis_key(scope))

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SIEM configuration found.",
        )

    logger.info("SIEM config deleted", extra={"scope": scope})
    return {"detail": "SIEM configuration removed."}


@router.post("/test")
async def test_siem_webhook(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fire a test event to the configured SIEM webhook.

    Returns: {success, status_code, latency_ms, error}
    """
    scope = _scope_id(current_user)
    redis = await get_redis()
    raw = await redis.get(_redis_key(scope))

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SIEM configuration found. Use POST /siem/configure first.",
        )

    config = json.loads(raw)
    fmt = config.get("format", "generic")

    test_alert = {
        "timestamp": "T+00:00",
        "severity": "informational",
        "source_system": "BreachReplay",
        "description": "Test event from BreachReplay SIEM integration",
        "raw_log": "BREACHREPLAY_TEST event_type=test source=breachreplay",
    }

    payload = format_alert_for_siem(test_alert, "BreachReplay Integration Test", fmt)
    result = await fire_webhook(config, payload, fmt)

    logger.info(
        "SIEM test fired",
        extra={
            "scope": scope,
            "format": fmt,
            "success": result["success"],
            "latency_ms": result["latency_ms"],
        },
    )

    return result


@router.get("/formats")
async def list_siem_formats():
    """Return all supported SIEM formats with descriptions and payload examples."""
    return SUPPORTED_FORMATS
