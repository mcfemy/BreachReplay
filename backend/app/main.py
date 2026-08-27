import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress

import redis.asyncio as aioredis
import sentry_sdk
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from jose import JWTError, jwt as jose_jwt
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.api import api_router
from app.core.config import settings
from app.core.logging import set_request_context, setup_logging
from app.core.redis import get_redis
from app.core.security import get_client_ip, limiter, sentry_before_send
from app.db.session import engine
from app.websocket.handlers import simulation_ws_handler, arena_ws_handler, arena_spectator_ws_handler, action_run_ws_handler

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        before_send=sentry_before_send,
        # Never send raw request bodies — they can contain tokens / PII
        send_default_pii=False,
    )

logger = logging.getLogger(__name__)

# Live Breach Events Phase 4 — "no one is left unmatched" safety net. See
# app.services.arena_matchmaking_service.sweep_closed_event_queues's
# docstring for why this must run as a background loop INSIDE this exact
# `backend` (uvicorn) process rather than a Celery task: only this process
# holds the real `manager.arena_queue` in-memory state. 20s keeps stragglers
# waiting no more than one extra poll interval past an event's official
# close, without hammering the DB on every tick.
_ARENA_EVENT_QUEUE_SWEEP_INTERVAL_SECONDS = 20


async def _arena_event_queue_sweep_loop():
    from app.db.session import AsyncSessionLocal
    from app.services import arena_matchmaking_service

    while True:
        await asyncio.sleep(_ARENA_EVENT_QUEUE_SWEEP_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                await arena_matchmaking_service.sweep_closed_event_queues(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad iteration (e.g. a transient DB hiccup) must never kill
            # this loop permanently — log and try again next tick.
            logger.exception("arena event queue sweep iteration failed")


# Phase 2 (action console core loop) — same "must run inside this exact
# backend process" reasoning as the Arena sweep above: only this process
# holds the real live app.services.action_run_store state. An abandoned
# run (tab closed, no more action.submit messages) would otherwise never
# get an ActionRun row at all — this sweep is what guarantees one, for
# both funnel data and Phase 4 ghost availability. 30s trades a slightly
# longer worst-case grace beyond the store's own 60s SWEEP_GRACE_SECONDS
# for not hammering the DB every tick, same tradeoff the Arena sweep makes.
_ACTION_RUN_SWEEP_INTERVAL_SECONDS = 30


async def _run_action_run_sweep_iteration() -> None:
    """One sweep pass: force-finalize expired runs, then broadcast run.end
    to whichever socket (if any) is still connected under each swept
    run_id — without this, a connected-but-slow player whose run the sweep
    force-finalizes would be left with a dead socket instead of their
    debrief. Factored out of the while-loop below so it can be exercised
    directly in tests without dealing with asyncio.sleep/an infinite loop,
    the same shape arena_matchmaking_service.sweep_closed_event_queues
    already has for the Arena sweep."""
    from app.db.session import AsyncSessionLocal
    from app.services.action_run_store import action_run_store
    from app.websocket.manager import manager, build_run_end_event

    async with AsyncSessionLocal() as db:
        finalized = await action_run_store.sweep_expired(db)
    for run_id, summary in finalized:
        await manager.broadcast(run_id, build_run_end_event(summary))


async def _action_run_sweep_loop():
    while True:
        await asyncio.sleep(_ACTION_RUN_SWEEP_INTERVAL_SECONDS)
        try:
            await _run_action_run_sweep_iteration()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("action run sweep iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    sweep_task = asyncio.create_task(_arena_event_queue_sweep_loop())
    action_run_sweep_task = asyncio.create_task(_action_run_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        action_run_sweep_task.cancel()
        with suppress(asyncio.CancelledError):
            await sweep_task
        with suppress(asyncio.CancelledError):
            await action_run_sweep_task


app = FastAPI(
    title="Breach Replay API",
    version="1.0.0",
    description="Cybersecurity incident response training platform",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ── Rate-limiter state ────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Security headers middleware ───────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        local_ws = "ws://localhost:8000 ws://127.0.0.1:8000" if settings.DEBUG else ""
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"connect-src 'self' wss://breachreplay.com {local_ws}; "
            "frame-ancestors 'none'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_context(request_id=request_id, user_id=None, session_id=None)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        # Vite is often bound to 127.0.0.1 (e.g. `npm run dev -- --host 127.0.0.1`);
        # browsers treat that Origin as distinct from localhost, so omit it and
        # credentialed XHR fails with a generic "Network Error".
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "https://breachreplay.com",
        "https://www.breachreplay.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/db")
async def health_db():
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - start) * 1000
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": type(e).__name__})


@app.get("/health/redis")
async def health_redis():
    start = time.perf_counter()
    redis_client = aioredis.from_url(settings.REDIS_URL)
    try:
        await redis_client.ping()
        latency_ms = (time.perf_counter() - start) * 1000
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": type(e).__name__})
    finally:
        await redis_client.aclose()


# ── WebSocket per-IP rate limiter — Redis sliding window (10 conn / 60 s) ─────
_WS_LIMIT = 10
_WS_WINDOW = 60


def _get_client_ip(websocket: WebSocket) -> str:
    """Same header order as HTTP slowapi (`get_client_ip`)."""
    return get_client_ip(websocket)


async def _ws_rate_allowed(r: aioredis.Redis, client_ip: str) -> bool:
    """Distributed sliding-window rate check backed by Redis sorted sets."""
    key = f"ws_rate:{client_ip}"
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - (_WS_WINDOW * 1000)
    member = str(uuid.uuid4())  # unique per request to avoid score collisions

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start_ms)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, _WS_WINDOW + 1)
    results = await pipe.execute()
    count = results[2]
    return count <= _WS_LIMIT


@app.websocket("/ws/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    # 1. Per-IP rate limit before completing the upgrade (BR-ARC-02)
    client_ip = _get_client_ip(websocket)
    r = await get_redis()
    if not await _ws_rate_allowed(r, client_ip):
        await websocket.close(code=4029)
        return

    # 2. Complete the HTTP → WebSocket upgrade
    await websocket.accept()

    # 3. First message must be an auth frame within 3 s (BR-SEC-01 / BR-BUG-01)
    #    This avoids putting the JWT in the URL (where it would appear in server logs).
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
        auth_msg = json.loads(raw)
        if auth_msg.get("type") != "auth":
            await websocket.close(code=4001)
            return
        token = auth_msg.get("token", "")
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
        await websocket.close(code=4001)
        return

    # 4. Verify JWT
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
    except (JWTError, ValueError):
        await websocket.close(code=4001)
        return

    await simulation_ws_handler(websocket, session_id, user_id)


@app.websocket("/ws/run/{run_id}")
async def websocket_action_run(websocket: WebSocket, run_id: str):
    """Phase 2 action console core loop connection. Identical rate-limit +
    deferred-auth-frame protocol to websocket_session above (copied, not
    shared, matching this file's existing convention of not factoring that
    block out between /ws/session and /ws/arena either) — see
    action_run_ws_handler's own docstring for what happens once a real
    user_id reaches it."""
    client_ip = _get_client_ip(websocket)
    r = await get_redis()
    if not await _ws_rate_allowed(r, client_ip):
        await websocket.close(code=4029)
        return

    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
        auth_msg = json.loads(raw)
        if auth_msg.get("type") != "auth":
            await websocket.close(code=4001)
            return
        token = auth_msg.get("token", "")
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
        await websocket.close(code=4001)
        return

    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
    except (JWTError, ValueError):
        await websocket.close(code=4001)
        return

    await action_run_ws_handler(websocket, run_id, user_id)


@app.websocket("/ws/arena/{match_id}")
async def websocket_arena(websocket: WebSocket, match_id: str):
    """Live Arena Mode match connection (Phase C). Mirrors /ws/session/{id}'s
    rate-limit + deferred-auth-frame pattern exactly (BR-ARC-02 / BR-SEC-01).

    Live Breach Events Phase 5: the first frame may ALSO be
    `{"type": "spectate"}` (no token) instead of `{"type": "auth", ...}` —
    routed to `arena_spectator_ws_handler`, which is itself hard-gated
    server-side on `match.event_id is not None` (re-derived from the DB,
    never trusted from this frame or anywhere else client-supplied) —
    spectating is meant to be public/anonymous ONLY for Live Event matches,
    so this branch does zero JWT verification. The `{"type": "auth", ...}`
    path below for real participants is completely unchanged."""
    # 1. Per-IP rate limit before completing the upgrade (BR-ARC-02) —
    #    applies identically to both the auth and spectate paths, since it
    #    runs before either first-frame type is even read.
    client_ip = _get_client_ip(websocket)
    r = await get_redis()
    if not await _ws_rate_allowed(r, client_ip):
        await websocket.close(code=4029)
        return

    # 2. Complete the HTTP → WebSocket upgrade
    await websocket.accept()

    # 3. First message must arrive within 3 s (BR-SEC-01 / BR-BUG-01) and be
    #    either {"type": "auth", "token": ...} or {"type": "spectate"}.
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
        first_msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
        await websocket.close(code=4001)
        return

    first_type = first_msg.get("type")

    if first_type == "spectate":
        # No JWT verification at all — public/anonymous by design. The
        # event_id gate lives inside arena_spectator_ws_handler itself
        # (re-checked against the DB), not here.
        await arena_spectator_ws_handler(websocket, match_id)
        return

    if first_type != "auth":
        await websocket.close(code=4001)
        return
    token = first_msg.get("token", "")

    # 4. Verify JWT
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
    except (JWTError, ValueError):
        await websocket.close(code=4001)
        return

    await arena_ws_handler(websocket, match_id, user_id)
