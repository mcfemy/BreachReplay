import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

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
from app.core.security import limiter, sentry_before_send
from app.db.session import engine
from app.websocket.handlers import simulation_ws_handler

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        before_send=sentry_before_send,
        # Never send raw request bodies — they can contain tokens / PII
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


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
            f"connect-src 'self' wss://breachreplay.io {local_ws}; "
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
        "https://breachreplay.io",
        "https://www.breachreplay.io",
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
    """Extract the true client IP, respecting standard proxy headers."""
    forwarded_for = websocket.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    cf_ip = websocket.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    return websocket.client.host if websocket.client else "unknown"


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
