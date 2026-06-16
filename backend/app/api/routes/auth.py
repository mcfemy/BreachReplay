import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    delete_password_reset_token,
    get_current_user,
    hash_password,
    limiter,
    revoke_all_user_sessions,
    revoke_refresh_token,
    store_password_reset_token,
    validate_password_reset_token,
    validate_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    ResetPasswordRequest,
    TokenOut,
    UserCreate,
    UserLogin,
    UserOut,
    UserUpdateRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

_DB_TO_API_ROLE = {"owner": "ciso", "viewer": "observer"}


def _user_out(user: User) -> UserOut:
    """Return a UserOut with DB-internal role aliases translated to Phase 3 schema names."""
    out = UserOut.model_validate(user)
    out.role = _DB_TO_API_ROLE.get(out.role, out.role)
    return out


async def _send_password_reset_email(email: str, reset_url: str) -> None:
    if not settings.SENDGRID_API_KEY:
        logger.info("SendGrid not configured; skipping reset email", extra={"email": email})
        return
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        message = Mail(
            from_email=settings.FROM_EMAIL,
            to_emails=email,
            subject="Reset your Breach Replay password",
            html_content=(
                f"<p>Click <a href='{reset_url}'>here</a> to reset your password.</p>"
                f"<p>This link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes. "
                "If you did not request a reset, ignore this email.</p>"
            ),
        )
        await asyncio.to_thread(sg.send, message)
    except Exception:
        logger.exception("Failed to send password reset email", extra={"email": email})


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, payload: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        organization_id=payload.organization_id,
    )
    db.add(user)
    await db.flush()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_out(user),
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
async def login(request: Request, payload: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user.last_login = datetime.utcnow()
    await db.commit()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_out(user),
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("20/minute")
async def refresh(request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    user_id = await validate_refresh_token(payload.refresh_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    # Rotate: revoke the old token, issue a fresh pair
    await revoke_refresh_token(payload.refresh_token)
    access_token = create_access_token({"sub": user.id})
    new_refresh_token = await create_refresh_token(str(user.id))
    return TokenOut(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=_user_out(user),
    )


@router.post("/logout", response_model=MessageResponse)
@limiter.limit("10/minute")
async def logout(request: Request, payload: LogoutRequest):
    await revoke_refresh_token(payload.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("3/minute")
async def forgot_password(request: Request, payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        token = str(uuid.uuid4())
        await store_password_reset_token(str(user.id), token)
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        await _send_password_reset_email(user.email, reset_url)
    # Always return 200 — never reveal whether the email exists
    return MessageResponse(message="If that email is registered, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def reset_password(request: Request, payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user_id = await validate_password_reset_token(payload.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user.hashed_password = hash_password(payload.new_password)
    await db.commit()
    # Revoke every active session so a hijacker cannot keep using old refresh tokens (BR-SEC-02)
    await revoke_all_user_sessions(user_id)
    await delete_password_reset_token(payload.token)
    return MessageResponse(message="Password reset successfully")


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    await db.commit()
    await db.refresh(current_user)
    return _user_out(current_user)
