"""Share-card text + PNG for public Action Console runs.

Leak-safety: both builders consume only public-DTO fields (plus Daily
challenge_number/streak on the authenticated mint path). The PNG
renderer is exercised with a poisoned DTO that still carries leftover
keys — it must not paint unknown-host identity, seed, or dossier
narrative into the image.
"""
import io

import pytest
from PIL import Image

from app.services.action_run_share import PUBLIC_DTO_KEYS, resolve_public_replay
from app.services.action_run_share_card import (
    OG_HEIGHT,
    OG_WIDTH,
    build_share_card_text,
    format_share_clock,
    render_share_card_png,
)
from tests.test_action_run_public_share import (
    FORBIDDEN_KEYS,
    _LEAK_IP,
    _LEAK_NARRATIVE,
    _LEAK_SEED,
    _LEAK_SOURCE_REF,
    _LEAK_USERNAME,
    _UNKNOWN_HOSTNAME,
    _auth_headers,
    _insert_completed_run,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_share_card_text_matches_daily_shape_and_points_at_r_token():
    card = build_share_card_text(
        scenario_title="Colonial Pipeline Replay",
        outcome="contained",
        score=800,
        duration_seconds=90,
        share_token="opaque-token",
        mode="scenario",
    )
    assert card == (
        "🔐 BreachReplay\n"
        "Colonial Pipeline Replay\n"
        "Score: 800 — CONTAINED\n"
        "Time: 1:30\n"
        "breachreplay.com/r/opaque-token"
    )
    assert "run_id" not in card
    assert "/daily" not in card


def test_share_card_text_daily_keeps_challenge_number_and_streak():
    card = build_share_card_text(
        scenario_title="SolarWinds",
        outcome="contained_at_cost",
        score=1200,
        duration_seconds=75,
        share_token="daily-tok",
        mode="daily",
        challenge_number=42,
        streak=3,
    )
    assert card.split("\n")[0] == "🔐 BreachReplay Daily #42"
    assert "🔥 3-day streak" in card
    assert "breachreplay.com/r/daily-tok" in card
    assert format_share_clock(75) == "1:15"


def test_share_card_text_omits_streak_of_one_like_daily():
    card = build_share_card_text(
        scenario_title="X",
        outcome="breached",
        score=0,
        duration_seconds=10,
        share_token="t",
        mode="daily",
        challenge_number=1,
        streak=1,
    )
    assert "streak" not in card


def test_png_renderer_rejects_a_non_public_payload():
    with pytest.raises(ValueError):
        render_share_card_png({"outcome": "contained"})


def test_png_is_valid_og_image_and_does_not_embed_excluded_strings():
    dto = {
        "outcome": "contained",
        "score": 800,
        "score_pct": 80,
        "duration_seconds": 90,
        "scenario_title": "Colonial Pipeline Replay",
        "mode": "scenario",
        "player_label": "Responder",
        "timeline": [],
        "hosts": [
            {"id": "unknown-1", "x": 80, "y": 60, "visibility": "unknown"},
            {
                "id": "known-1",
                "hostname": "CORP-WKS-22",
                "role": "workstation",
                "network_segment_id": "lan",
                "compromise_level": "none",
                "isolated": True,
                "x": 230,
                "y": 60,
            },
        ],
        "edges": [],
        "techniques_encountered": [],
        # Poison — must be ignored even if a caller stuffed them on.
        "seed": _LEAK_SEED,
        "hidden_iocs": [{"matches_on": {"ip": _LEAK_IP}}],
        "incident_narrative": _LEAK_NARRATIVE,
        "source_reference": _LEAK_SOURCE_REF,
        "action_log": [{"target": _LEAK_USERNAME}],
    }
    assert set(k for k in dto if k in PUBLIC_DTO_KEYS) == PUBLIC_DTO_KEYS

    png = render_share_card_png(dto)
    assert png.startswith(_PNG_MAGIC)
    img = Image.open(io.BytesIO(png))
    assert img.size == (OG_WIDTH, OG_HEIGHT)
    assert img.format == "PNG"

    blob = png
    assert str(_LEAK_SEED).encode() not in blob
    assert _LEAK_IP.encode() not in blob
    assert _LEAK_USERNAME.encode() not in blob
    assert _UNKNOWN_HOSTNAME.encode() not in blob
    assert _LEAK_NARRATIVE.encode() not in blob
    assert _LEAK_SOURCE_REF.encode() not in blob
    assert b"SECRET-DC" not in blob


@pytest.mark.asyncio
async def test_public_card_png_404s_for_unknown_token(client):
    resp = await client.get("/api/v1/action-runs/public/replay/not-a-real-token/card.png")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Replay not found"


@pytest.mark.asyncio
async def test_public_unfurl_404s_for_unknown_token(client):
    resp = await client.get("/api/v1/action-runs/public/unfurl/not-a-real-token")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Replay not found"


@pytest.mark.asyncio
async def test_public_card_png_and_unfurl_use_the_same_locked_dto(
    client, db, test_user, approved_scenario,
):
    run = await _insert_completed_run(
        db, user_id=test_user["user"].id, scenario_id=approved_scenario.id,
    )
    mint = await client.post(
        f"/api/v1/action-runs/{run.id}/share",
        headers=_auth_headers(test_user["token"]),
    )
    token = mint.json()["share_token"]

    dto = await resolve_public_replay(db, token)
    assert dto is not None
    leaked = set()
    def walk(obj):
        if isinstance(obj, dict):
            leaked.update(set(obj) & FORBIDDEN_KEYS)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(dto)
    assert leaked == set()

    png_resp = await client.get(f"/api/v1/action-runs/public/replay/{token}/card.png")
    assert png_resp.status_code == 200
    assert png_resp.headers["content-type"].startswith("image/png")
    assert png_resp.content.startswith(_PNG_MAGIC)
    assert str(_LEAK_SEED).encode() not in png_resp.content
    assert _LEAK_IP.encode() not in png_resp.content
    assert _UNKNOWN_HOSTNAME.encode() not in png_resp.content
    assert _LEAK_NARRATIVE.encode() not in png_resp.content
    assert test_user["user"].email.encode() not in png_resp.content
    assert test_user["user"].id.encode() not in png_resp.content

    unfurl = await client.get(f"/api/v1/action-runs/public/unfurl/{token}")
    assert unfurl.status_code == 200
    html = unfurl.text
    assert 'property="og:image"' in html
    assert f"/action-runs/public/replay/{token}/card.png" in html
    assert 'name="twitter:card"' in html
    assert "summary_large_image" in html
    assert approved_scenario.title in html
    assert str(_LEAK_SEED) not in html
    assert _LEAK_IP not in html
    assert _LEAK_NARRATIVE not in html
    assert test_user["user"].email not in html
    assert run.id not in html
