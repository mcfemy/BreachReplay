from datetime import datetime, timedelta

import pytest
from jose import jwt as jose_jwt

from app.core.config import settings
from app.core.security import limiter

pytestmark = pytest.mark.asyncio


async def _start(client):
    resp = await client.post("/api/v1/teaser/start")
    assert resp.status_code == 200
    return resp.json()


async def test_start_returns_playable_payload_without_leaking_the_answer(client):
    data = await _start(client)
    assert "teaser_token" in data
    assert data["countdown_seconds"] == 60
    assert data["decision"]["node_choices"] == ["MAIL-01", "DC-01", "FIN-03"]
    assert len(data["nodes"]) >= 6

    # Never expose hidden_iocs / full scenario internals through this surface.
    body = str(data)
    assert "hidden_iocs" not in body
    assert "correct_index" not in body
    assert "rationale" not in body
    assert "consequence_if_wrong" not in body


async def test_answer_correct_choice_contains_the_source_node(client):
    data = await _start(client)
    resp = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": data["teaser_token"],
        "chosen_node_id": "MAIL-01",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["correct"] is True
    assert body["node_states"] == {"MAIL-01": "contained"}


async def test_answer_wrong_choice_bleeds_to_two_more_hosts(client):
    data = await _start(client)
    resp = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": data["teaser_token"],
        "chosen_node_id": "DC-01",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["correct"] is False
    assert body["node_states"] == {"MAIL-01": "compromised", "DC-01": "compromised", "FIN-03": "compromised"}


async def test_answer_rejects_a_node_not_offered_as_a_choice(client):
    data = await _start(client)
    resp = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": data["teaser_token"],
        "chosen_node_id": "HISTORIAN-01",
    })
    assert resp.status_code == 400


async def test_answer_rejects_a_tampered_or_missing_token(client):
    resp = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": "not-a-real-token",
        "chosen_node_id": "MAIL-01",
    })
    assert resp.status_code == 401


async def test_answer_rejects_a_real_user_access_token(client, test_user):
    """A real login access_token must never double as a teaser_token — the
    two token families are deliberately unrelated (see teaser.py docstring)."""
    resp = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": test_user["token"],
        "chosen_node_id": "MAIL-01",
    })
    assert resp.status_code == 401


async def test_claim_requires_authentication(client):
    data = await _start(client)
    resp = await client.post("/api/v1/teaser/claim", json={"teaser_token": data["teaser_token"]})
    assert resp.status_code == 403


async def test_claim_unlocks_teaser_survivor_after_a_completed_run(client, test_user):
    data = await _start(client)
    await client.post("/api/v1/teaser/answer", json={
        "teaser_token": data["teaser_token"],
        "chosen_node_id": "MAIL-01",
    })
    resp = await client.post(
        "/api/v1/teaser/claim",
        json={"teaser_token": data["teaser_token"]},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["claimed"] is True
    assert body["achievement_unlocked"] is True

    # NOTE: repeat-claim idempotency (unlock_achievement no-ops on an
    # already-unlocked key) is a property of app.services.xp_service, not of
    # this route, and isn't re-verified here: unlock_achievement persists
    # User.achievements via `CAST(:a AS jsonb)` raw SQL, which is correct
    # against the real Postgres column type but round-trips incorrectly
    # under this test suite's SQLite fixture (NUMERIC-affinity CAST turns
    # the JSON array text into 0), making the achievements list read back
    # empty on every subsequent SQLite-backed request regardless of what
    # this route does. A second /teaser/claim call is still confirmed safe
    # (200, no error) below.
    resp2 = await client.post(
        "/api/v1/teaser/claim",
        json={"teaser_token": data["teaser_token"]},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp2.status_code == 200


async def test_claim_without_a_completed_run_returns_404(client, test_user):
    orphan_token = jose_jwt.encode(
        {"typ": "teaser", "tid": "orphan-token-id", "exp": datetime.utcnow() + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = await client.post(
        "/api/v1/teaser/claim",
        json={"teaser_token": orphan_token},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 404


async def test_teaser_start_is_rate_limited_per_ip(client):
    limiter.enabled = True
    try:
        last_status = None
        for _ in range(25):
            resp = await client.post("/api/v1/teaser/start")
            last_status = resp.status_code
            if last_status == 429:
                break
        assert last_status == 429
    finally:
        limiter.enabled = False
