import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import sentry_sdk
from fastapi import FastAPI, WebSocket, Query
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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "connect-src 'self' wss://breachreplay.io; "
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


# ── WebSocket per-IP rate limiter (10 new connections / 60 s) ─────────────────
_ws_connect_log: dict[str, list[float]] = defaultdict(list)
_WS_LIMIT = 10
_WS_WINDOW = 60


def _ws_rate_allowed(client_ip: str) -> bool:
    now = time.monotonic()
    log = _ws_connect_log[client_ip]
    log[:] = [t for t in log if now - t < _WS_WINDOW]
    if not log and client_ip in _ws_connect_log:
        del _ws_connect_log[client_ip]
    if len(log) >= _WS_LIMIT:
        return False
    _ws_connect_log[client_ip].append(now)
    return True


@app.websocket("/ws/session/{session_id}")
async def websocket_session(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(..., description="JWT access token"),
):
    # 1. Per-IP rate limit before the handshake is completed
    client_ip = websocket.client.host if websocket.client else "unknown"
    if not _ws_rate_allowed(client_ip):
        await websocket.close(code=4029)  # 4029 = Too Many Requests (app-level)
        return

    # 2. Verify JWT before accepting the WebSocket upgrade
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
    except (JWTError, ValueError):
        await websocket.close(code=4001)  # 4001 = Unauthorized
        return

    await simulation_ws_handler(websocket, session_id, user_id)
