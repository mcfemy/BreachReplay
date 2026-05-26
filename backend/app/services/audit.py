from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    action: str,
    user_id: str = None,
    organization_id: str = None,
    ip_address: str = None,
    user_agent: str = None,
    details: dict = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        organization_id=organization_id,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )
    db.add(log)
    await db.flush()  # Stage in the session; caller owns the commit
    return log


def get_client_info(request: Request) -> tuple[str, str]:
    """Extract IP Address and User Agent safely from a FastAPI request."""
    ip = request.headers.get("x-forwarded-for")
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    return ip, ua
