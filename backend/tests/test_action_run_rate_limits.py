"""Rate limits on Action Console create + public share routes.

Mirrors test_teaser_start_is_rate_limited_per_ip: flip the session-wide
limiter back on, burst until 429, restore.

Also pins the proxy-IP bug the readiness audit flagged: stock
slowapi `get_remote_address` is the TCP peer, so behind nginx every
visitor shared one bucket. `get_client_ip` must key on X-Forwarded-For
/ CF-Connecting-IP the way the WS limiter already did.
"""
from starlette.requests import Request

import pytest
from slowapi.util import get_remote_address

from app.core.security import get_client_ip, limiter


def _request(*, peer: str, extra_headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    headers = list(extra_headers or [])
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 54321),
        "server": ("test", 80),
    })


def test_stock_get_remote_address_ignores_proxy_headers():
    """The existing HTTP limiter key — proven, not assumed.

    A request whose socket peer is the proxy (127.0.0.1) but whose
    X-Forwarded-For / CF-Connecting-IP name a real client must still
    key as the peer. That is why auth/teaser limits collapsed behind
    nginx before get_client_ip replaced this.
    """
    req = _request(
        peer="127.0.0.1",
        extra_headers=[
            (b"x-forwarded-for", b"203.0.113.50, 172.16.0.2"),
            (b"cf-connecting-ip", b"203.0.113.50"),
        ],
    )
    assert get_remote_address(req) == "127.0.0.1"
    assert get_client_ip(req) == "203.0.113.50"


def test_get_client_ip_falls_back_to_cf_connecting_ip():
    req = _request(
        peer="10.0.0.1",
        extra_headers=[(b"cf-connecting-ip", b"198.51.100.9")],
    )
    assert get_client_ip(req) == "198.51.100.9"


def test_get_client_ip_falls_back_to_socket_peer():
    req = _request(peer="192.0.2.10")
    assert get_client_ip(req) == "192.0.2.10"


async def _burst_until_429(client, method: str, url: str, *, headers=None, json=None, n: int) -> int | None:
    last = None
    for _ in range(n):
        resp = await client.request(method, url, headers=headers, json=json)
        last = resp.status_code
        if last == 429:
            return last
    return last


@pytest.mark.asyncio
async def test_public_replay_json_is_rate_limited_per_ip(client):
    limiter.enabled = True
    try:
        last = await _burst_until_429(
            client, "GET", "/api/v1/action-runs/public/replay/not-a-real-token", n=65,
        )
        assert last == 429
    finally:
        limiter.enabled = False


@pytest.mark.asyncio
async def test_public_card_png_is_rate_limited_per_ip(client):
    limiter.enabled = True
    try:
        last = await _burst_until_429(
            client, "GET", "/api/v1/action-runs/public/replay/not-a-real-token/card.png", n=35,
        )
        assert last == 429
    finally:
        limiter.enabled = False


@pytest.mark.asyncio
async def test_public_unfurl_is_rate_limited_per_ip(client):
    limiter.enabled = True
    try:
        last = await _burst_until_429(
            client, "GET", "/api/v1/action-runs/public/unfurl/not-a-real-token", n=35,
        )
        assert last == 429
    finally:
        limiter.enabled = False


@pytest.mark.asyncio
async def test_create_action_run_is_rate_limited_per_ip(client, test_user):
    limiter.enabled = True
    try:
        last = await _burst_until_429(
            client, "POST", "/api/v1/action-runs",
            headers={"Authorization": f"Bearer {test_user['token']}"},
            json={"scenario_id": "not-a-real-scenario"},
            n=15,
        )
        assert last == 429
    finally:
        limiter.enabled = False


@pytest.mark.asyncio
async def test_public_replay_limit_is_per_forwarded_client_not_shared(client):
    """After the key_func fix, two X-Forwarded-For values are two buckets.

    Exhaust the 60/min JSON limit as 203.0.113.10, then the same path as
    203.0.113.20 must still be a normal 404 — not a shared 429.
    """
    limiter.enabled = True
    try:
        last = None
        for _ in range(65):
            resp = await client.get(
                "/api/v1/action-runs/public/replay/not-a-real-token",
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            last = resp.status_code
            if last == 429:
                break
        assert last == 429

        other = await client.get(
            "/api/v1/action-runs/public/replay/not-a-real-token",
            headers={"X-Forwarded-For": "203.0.113.20"},
        )
        assert other.status_code == 404
    finally:
        limiter.enabled = False
