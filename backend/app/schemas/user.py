from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from typing import Optional
from datetime import datetime
import re

# BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4's 8 verbs, verbatim — mirrors
# backend/app/services/verb_engine.py's VERB_COSTS keys. Duplicated here
# (schemas layer has no dependency on services) rather than imported, purely
# to validate UserUpdateRequest.seen_verb_coachmarks against real verb names.
_VALID_COACHMARK_VERBS = frozenset({
    "scan_network", "query_logs", "isolate", "image_disk",
    "interview_user", "block_ip", "reset_creds", "escalate",
})

_PASSWORD_RE = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]).{8,128}$'
)
_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=100)
    organization_id: Optional[str] = Field(default=None, max_length=36)
    # CMMC Evidence Layer invitation redemption (build-order item 2):
    # register+redeem in one step, mirroring the organization_id pattern
    # above. See app.services.cmmc_invites and the register() handler in
    # app/api/routes/auth.py for the email-binding check this enables — a
    # forwarded invite link must not grant access to a different email.
    invite_token: Optional[str] = Field(default=None, max_length=128)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be 8-128 characters and include uppercase, "
                "lowercase, digit, and special character"
            )
        return v

    @field_validator("organization_id")
    @classmethod
    def validate_org_uuid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _UUID_RE.match(v):
            raise ValueError("organization_id must be a valid UUID")
        return v


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    organization_id: Optional[str]
    mfa_enabled: bool = False
    has_seen_console_intro: bool = False
    seen_verb_coachmarks: list[str] = Field(default_factory=list)
    has_acknowledged_racing_notice: bool = False
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be 8-128 characters and include uppercase, "
                "lowercase, digit, and special character"
            )
        return v


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, max_length=100)
    has_seen_console_intro: Optional[bool] = None
    # Full-replace, same contract as has_seen_console_intro above — the
    # client always sends the complete updated array (it already holds the
    # current one from /auth/me), not a single verb to append.
    seen_verb_coachmarks: Optional[list[str]] = Field(default=None, max_length=8)
    has_acknowledged_racing_notice: Optional[bool] = None

    @field_validator("seen_verb_coachmarks")
    @classmethod
    def validate_coachmark_verbs(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and not set(v).issubset(_VALID_COACHMARK_VERBS):
            raise ValueError("seen_verb_coachmarks contains an unknown verb")
        return v


class MessageResponse(BaseModel):
    message: str


# ── MFA / TOTP Schemas ────────────────────────────────────────────────────────

class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str  # data URL: data:image/png;base64,...
    backup_codes: list[str]  # returned once; store them safely


class MFAEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=8)


class MFAVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mfa_token: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=8)


class MFARequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str


class MFAStatusResponse(BaseModel):
    mfa_enabled: bool
