"""
Slack slash command endpoint.

Slack posts application/x-www-form-urlencoded to this route when a user types
/breach-replay in their workspace.  We verify the signature then return a
formatted scenario snippet immediately (< 3 s Slack timeout).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.scenario import Scenario
from app.services.slack_service import build_scenario_snippet_blocks, verify_slack_signature

router = APIRouter(prefix="/slack", tags=["slack"])


@router.post("/command")
async def slash_command(
    request: Request,
    text: str = Form(default=""),
    command: str = Form(default="/breach-replay"),
    x_slack_request_timestamp: str = Header(default=""),
    x_slack_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    if not verify_slack_signature(body, x_slack_request_timestamp, x_slack_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature")

    # Pick a random approved public scenario
    result = await db.execute(
        select(Scenario)
        .where(Scenario.status == "approved", Scenario.is_private == False)  # noqa: E712
        .order_by(func.random())
        .limit(1)
    )
    scenario = result.scalar_one_or_none()

    if not scenario:
        return {
            "response_type": "ephemeral",
            "text": "No scenarios available yet. Check back after the pipeline runs.",
        }

    blocks = build_scenario_snippet_blocks(
        {
            "title": scenario.title,
            "difficulty": scenario.difficulty,
            "industry_vertical": scenario.industry_vertical,
            "mitre_techniques": scenario.mitre_techniques,
            "nist_controls": scenario.nist_controls,
            "estimated_minutes": scenario.estimated_minutes,
        }
    )

    return {
        "response_type": "in_channel",
        "blocks": blocks,
    }
