"""
Slack integration service — incoming webhook + slash command support.

To enable:
  1. Create a Slack App at api.slack.com/apps
  2. Enable Incoming Webhooks and copy the URL → SLACK_WEBHOOK_URL in .env
  3. Add a Slash Command (/breach-replay) pointing to POST /api/v1/slack/command
  4. Copy the Signing Secret → SLACK_SIGNING_SECRET in .env
  5. Set SLACK_CHANNEL_ID to the channel ID for weekly digests
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_webhook_message(text: str, blocks: Optional[list] = None) -> bool:
    """Post a message to the configured Slack channel via incoming webhook."""
    if not settings.SLACK_WEBHOOK_URL:
        logger.info("SLACK_WEBHOOK_URL not configured — skipping Slack message")
        return False
    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = requests.post(settings.SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Slack webhook message")
        return False


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify a Slack request signature to prevent spoofed slash commands."""
    if not settings.SLACK_SIGNING_SECRET:
        # Reject all Slack requests when no signing secret is configured — prevents
        # open access to scenario data in deployments that haven't set up Slack.
        logger.warning("SLACK_SIGNING_SECRET not configured — rejecting Slack request")
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False  # replay attack window
        base = f"v0:{timestamp}:{body.decode()}"
        expected = "v0=" + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            base.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def build_scenario_snippet_blocks(scenario: dict) -> list:
    """Build Slack Block Kit blocks for a weekly scenario snippet."""
    title = scenario.get("title", "Untitled Scenario")
    difficulty = scenario.get("difficulty", "practitioner").upper()
    industry = scenario.get("industry_vertical") or "General"
    mitre = (scenario.get("mitre_techniques") or [])[:3]
    nist = (scenario.get("nist_controls") or [])[:2]
    estimated = scenario.get("estimated_minutes", 45)

    mitre_tags = " ".join(f"`{t}`" for t in mitre) if mitre else "_Not tagged_"
    nist_tags = " ".join(f"`{c}`" for c in nist) if nist else "_Not tagged_"

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⬡ BreachReplay — Weekly Scenario Spotlight",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{title}*\n{industry} · {difficulty} · {estimated}min",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Launch Simulation"},
                "style": "danger",
                "url": f"{settings.FRONTEND_URL}/scenarios",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*MITRE ATT&CK*\n{mitre_tags}"},
                {"type": "mrkdwn", "text": f"*NIST Controls*\n{nist_tags}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "React with 🚨 if your team should run this scenario this week.",
                }
            ],
        },
    ]
