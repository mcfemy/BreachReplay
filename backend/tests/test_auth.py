import pytest

pytestmark = pytest.mark.asyncio


async def test_register_success(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "register@example.com",
        "password": "StrongPass1!",
        "full_name": "Register User",
    })
    assert response.status_code == 201
    assert "access_token" in response.json()


async def test_register_duplicate_email(client):
    payload = {
        "email": "duplicate@example.com",
        "password": "StrongPass1!",
        "full_name": "Duplicate User",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 400


async def test_register_weak_password(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "weak@example.com",
        "password": "WeakPass1",
        "full_name": "Weak User",
    })
    assert response.status_code == 422


async def test_login_success(client):
    payload = {
        "email": "login@example.com",
        "password": "StrongPass1!",
        "full_name": "Login User",
    }
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post("/api/v1/auth/login", json={
        "email": payload["email"],
        "password": payload["password"],
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_login_invalid_credentials(client):
    payload = {
        "email": "invalid-login@example.com",
        "password": "StrongPass1!",
        "full_name": "Invalid Login User",
    }
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post("/api/v1/auth/login", json={
        "email": payload["email"],
        "password": "WrongPass1!",
    })
    assert response.status_code == 401


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
