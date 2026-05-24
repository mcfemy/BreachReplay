import uuid

import pytest

pytestmark = pytest.mark.asyncio

# ── helpers ──────────────────────────────────────────────────────────────────

_REG_COUNTER = 0


def _unique_email(prefix: str) -> str:
    global _REG_COUNTER
    _REG_COUNTER += 1
    return f"{prefix}-{_REG_COUNTER}@example.com"


async def _register(client, prefix: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": _unique_email(prefix),
        "password": "StrongPass1!",
        "full_name": f"{prefix} User",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── register ─────────────────────────────────────────────────────────────────

async def test_register_success(client):
    data = await _register(client, "register")
    assert "access_token" in data
    assert "refresh_token" in data


async def test_register_duplicate_email(client):
    payload = {
        "email": _unique_email("dup"),
        "password": "StrongPass1!",
        "full_name": "Duplicate User",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 400


async def test_register_weak_password(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": _unique_email("weak"),
        "password": "WeakPass1",
        "full_name": "Weak User",
    })
    assert response.status_code == 422


# ── login ────────────────────────────────────────────────────────────────────

async def test_login_success(client):
    tokens = await _register(client, "login")
    response = await client.post("/api/v1/auth/login", json={
        "email": tokens["user"]["email"],
        "password": "StrongPass1!",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_login_invalid_credentials(client):
    tokens = await _register(client, "invalid-login")
    response = await client.post("/api/v1/auth/login", json={
        "email": tokens["user"]["email"],
        "password": "WrongPass1!",
    })
    assert response.status_code == 401


# ── me ───────────────────────────────────────────────────────────────────────

async def test_me_authenticated(client, test_user):
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == test_user["user"].email


async def test_me_unauthenticated(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 403


# ── refresh ──────────────────────────────────────────────────────────────────

async def test_refresh_token_success(client):
    tokens = await _register(client, "refresh")
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # Token was rotated — original should be invalid now
    reuse = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert reuse.status_code == 401


async def test_refresh_token_invalid(client):
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": str(uuid.uuid4()),
    })
    assert response.status_code == 401


# ── logout ───────────────────────────────────────────────────────────────────

async def test_logout_revokes_refresh_token(client):
    tokens = await _register(client, "logout")
    logout_resp = await client.post("/api/v1/auth/logout", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert logout_resp.status_code == 200
    # Revoked token cannot be used to refresh
    refresh_resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert refresh_resp.status_code == 401


# ── forgot / reset password ───────────────────────────────────────────────────

async def test_forgot_password_always_200(client):
    # Known email
    tokens = await _register(client, "forgot")
    resp = await client.post("/api/v1/auth/forgot-password", json={
        "email": tokens["user"]["email"],
    })
    assert resp.status_code == 200

    # Unknown email — must also return 200 (no enumeration)
    resp = await client.post("/api/v1/auth/forgot-password", json={
        "email": "nobody@nowhere.invalid",
    })
    assert resp.status_code == 200


async def test_reset_password_success(client, test_user):
    from app.core.security import store_password_reset_token

    token = str(uuid.uuid4())
    await store_password_reset_token(str(test_user["user"].id), token)

    resp = await client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "NewStrongPass2@",
    })
    assert resp.status_code == 200

    # Can now log in with the new password
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": test_user["user"].email,
        "password": "NewStrongPass2@",
    })
    assert login_resp.status_code == 200


async def test_reset_password_invalid_token(client):
    resp = await client.post("/api/v1/auth/reset-password", json={
        "token": str(uuid.uuid4()),
        "new_password": "NewStrongPass2@",
    })
    assert resp.status_code == 400


async def test_reset_password_token_single_use(client, test_user):
    from app.core.security import store_password_reset_token

    token = str(uuid.uuid4())
    await store_password_reset_token(str(test_user["user"].id), token)

    await client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "NewStrongPass3#",
    })
    # Second use of same token must fail
    second = await client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "AnotherPass4$",
    })
    assert second.status_code == 400
