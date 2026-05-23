import re
import logging
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.requests import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

limiter = Limiter(key_func=get_remote_address)

# Patterns that must never appear in logs, errors, or Sentry payloads.
_SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|secret[_-]?key|password|passwd|token|bearer)\s*[=:]\s*\S+'),
    re.compile(r'sk-ant-[A-Za-z0-9\-_]{20,}'),           # Anthropic key
    re.compile(r'AKIA[0-9A-Z]{16}'),                       # AWS access key
    re.compile(r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*\S+'),
    re.compile(r'[a-zA-Z][a-zA-Z0-9+\-.]*://[^:@/\s]+:[^@/\s]+@'),  # DSN with password
    re.compile(r'SG\.[A-Za-z0-9\-_]{22,}\.[A-Za-z0-9\-_]{43,}'),    # SendGrid key
    re.compile(r'eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'),  # JWT token
]


def _scrub_secrets(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def sanitize_error(exc: Exception, context: str = "") -> str:
    """Return a scrubbed error string safe for logs. Never expose to API clients directly."""
    raw = str(exc)
    scrubbed = _scrub_secrets(raw)
    if context:
        logger.error("Error in %s: %s", context, scrubbed)
    return scrubbed


def sentry_before_send(event: dict, hint: dict) -> dict:
    """Sentry before_send hook — strip secrets from every payload before transmission."""
    if "request" in event:
        headers = event["request"].get("headers", {})
        for key in list(headers.keys()):
            if key.lower() in ("authorization", "cookie", "x-api-key", "x-auth-token"):
                headers[key] = "[Filtered]"
        qs = event["request"].get("query_string", "")
        if qs:
            event["request"]["query_string"] = re.sub(r'token=[^&]+', 'token=[Filtered]', qs)

    for exc_val in event.get("exception", {}).get("values", []):
        if exc_val.get("value"):
            exc_val["value"] = _scrub_secrets(exc_val["value"])

    for crumb in event.get("breadcrumbs", {}).get("values", []):
        if crumb.get("message"):
            crumb["message"] = _scrub_secrets(crumb["message"])
        if isinstance(crumb.get("data"), dict):
            for k, v in crumb["data"].items():
                if isinstance(v, str):
                    crumb["data"][k] = _scrub_secrets(v)

    return event


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
