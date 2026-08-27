"""Tests for GET /api/v1/unsubscribe — beat-notification opt-out."""
import pytest
from sqlalchemy import select

from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _register(client, prefix: str = "unsub") -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{id(client)}@example.com",
        "password": "StrongPass1!",
        "full_name": "Unsub User",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _user_token(db, user_id: str) -> str:
    user = await db.scalar(select(User).where(User.id == user_id))
    assert user is not None
    assert user.email_unsubscribe_token
    return user.email_unsubscribe_token


async def test_unsubscribe_valid_token_disables_beat_notifications(client, db):
    data = await _register(client, "valid")
    token = await _user_token(db, data["user"]["id"])

    resp = await client.get(f"/api/v1/unsubscribe?token={token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["beat_notifications_enabled"] is False
    assert "unsubscribed" in body["message"].lower()

    user = await db.scalar(select(User).where(User.id == data["user"]["id"]))
    assert user.beat_notifications_enabled is False


async def test_unsubscribe_invalid_token_returns_404(client):
    resp = await client.get("/api/v1/unsubscribe?token=not-a-real-unsubscribe-token-value")
    assert resp.status_code == 404


async def test_unsubscribe_already_unsubscribed_is_idempotent(client, db):
    data = await _register(client, "again")
    token = await _user_token(db, data["user"]["id"])

    first = await client.get(f"/api/v1/unsubscribe?token={token}")
    assert first.status_code == 200

    second = await client.get(f"/api/v1/unsubscribe?token={token}")
    assert second.status_code == 200
    body = second.json()
    assert body["beat_notifications_enabled"] is False
    assert "already unsubscribed" in body["message"].lower()
