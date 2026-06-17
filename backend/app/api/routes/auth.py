import asyncio
import uuid
from datetime import datetime

import httpx as _httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
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


def _build_redirect_url(provider: str) -> str:
    return f"{settings.FRONTEND_URL}/api/v1/auth/{provider}/callback"


# ── Google OAuth SSO ───────────────────────────────────────────────────────────

@router.get("/google")
async def google_login():
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google OAuth not configured")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _build_redirect_url("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url)


@router.get("/google/callback")
@limiter.limit("20/minute")
async def google_callback(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth not configured")

    async with _httpx.AsyncClient() as client_http:
        token_resp = await client_http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _build_redirect_url("google"),
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(400, "Google token exchange failed")

    token_data = token_resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(400, "No id_token in Google response")

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        idinfo = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(400, "Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo.get("email")
    full_name = idinfo.get("name")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.google_id = google_id
        else:
            user = User(
                email=email,
                hashed_password=hash_password(str(uuid.uuid4())),
                full_name=full_name,
                google_id=google_id,
            )
            db.add(user)
            await db.flush()

    user.last_login = datetime.utcnow()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?access_token={access_token}&refresh_token={refresh_token}"
    )


# ── Microsoft (Azure AD / Entra ID) OAuth SSO ─────────────────────────────────

@router.get("/microsoft")
async def microsoft_login():
    if not settings.MICROSOFT_CLIENT_ID:
        raise HTTPException(503, "Microsoft OAuth not configured")
    import urllib.parse
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "redirect_uri": _build_redirect_url("microsoft"),
        "response_type": "code",
        "response_mode": "query",
        "scope": "openid email profile",
    }
    base = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
    url = base + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/microsoft/callback")
@limiter.limit("20/minute")
async def microsoft_callback(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
        raise HTTPException(503, "Microsoft OAuth not configured")

    async with _httpx.AsyncClient() as client_http:
        token_resp = await client_http.post(
            f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _build_redirect_url("microsoft"),
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(400, "Microsoft token exchange failed")

    token_data = token_resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(400, "No id_token in Microsoft response")

    # Decode claims from the signed id_token (trusted source — received via HTTPS from Microsoft)
    try:
        from jose import jwt as jose_jwt
        claims = jose_jwt.get_unverified_claims(id_token_str)
    except Exception:
        raise HTTPException(400, "Invalid Microsoft token")

    microsoft_id = claims.get("oid") or claims.get("sub")
    email = claims.get("email") or claims.get("preferred_username")
    full_name = claims.get("name")

    if not microsoft_id or not email:
        raise HTTPException(400, "Could not extract identity from Microsoft token")

    result = await db.execute(select(User).where(User.microsoft_id == microsoft_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.microsoft_id = microsoft_id
        else:
            user = User(
                email=email,
                hashed_password=hash_password(str(uuid.uuid4())),
                full_name=full_name,
                microsoft_id=microsoft_id,
            )
            db.add(user)
            await db.flush()

    user.last_login = datetime.utcnow()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?access_token={access_token}&refresh_token={refresh_token}"
    )


# ── GitHub OAuth SSO ───────────────────────────────────────────────────────────

@router.get("/github")
async def github_login():
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(503, "GitHub OAuth not configured")
    import urllib.parse
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": _build_redirect_url("github"),
        "scope": "read:user user:email",
    }
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/github/callback")
@limiter.limit("20/minute")
async def github_callback(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(503, "GitHub OAuth not configured")

    async with _httpx.AsyncClient() as client_http:
        token_resp = await client_http.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _build_redirect_url("github"),
            },
            headers={"Accept": "application/json"},
        )
    if token_resp.status_code != 200:
        raise HTTPException(400, "GitHub token exchange failed")

    gh_access_token = token_resp.json().get("access_token")
    if not gh_access_token:
        raise HTTPException(400, "No access_token in GitHub response")

    async with _httpx.AsyncClient() as client_http:
        user_resp = await client_http.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {gh_access_token}", "Accept": "application/json"},
        )
    if user_resp.status_code != 200:
        raise HTTPException(400, "Failed to fetch GitHub user info")

    gh_user = user_resp.json()
    github_id = str(gh_user.get("id"))
    full_name = gh_user.get("name") or gh_user.get("login")
    email = gh_user.get("email")

    # GitHub users may keep email private — fetch from emails endpoint
    if not email:
        async with _httpx.AsyncClient() as client_http:
            emails_resp = await client_http.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {gh_access_token}", "Accept": "application/json"},
            )
        if emails_resp.status_code == 200:
            primary = next(
                (e["email"] for e in emails_resp.json() if e.get("primary") and e.get("verified")),
                None,
            )
            email = primary

    if not email:
        raise HTTPException(400, "Could not retrieve a verified email from GitHub")

    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.github_id = github_id
        else:
            user = User(
                email=email,
                hashed_password=hash_password(str(uuid.uuid4())),
                full_name=full_name,
                github_id=github_id,
            )
            db.add(user)
            await db.flush()

    user.last_login = datetime.utcnow()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?access_token={access_token}&refresh_token={refresh_token}"
    )
