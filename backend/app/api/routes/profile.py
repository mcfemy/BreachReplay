"""
User profile, XP, achievements, and global leaderboard.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.models.user import User
from app.core.security import get_current_user
from app.services.xp_service import CAREER_TIERS, ACHIEVEMENTS, compute_tier, xp_to_next_tier

router = APIRouter(prefix="/profile", tags=["profile"])

# Separate router (distinct prefix) for the Live Breach Events Phase 1
# public-profile opt-in settings — kept in this file since it's the existing
# home of user-profile-adjacent concerns, but registered under /users in
# app/api/__init__.py to match the plan's PATCH /users/me/public-profile path.
users_router = APIRouter(prefix="/users", tags=["users"])


def _tier_progress(xp: int) -> dict:
    current = compute_tier(xp)
    tiers = CAREER_TIERS
    idx = next((i for i, t in enumerate(tiers) if t["key"] == current["key"]), 0)
    next_tier = tiers[idx + 1] if idx + 1 < len(tiers) else None
    if next_tier:
        tier_xp = xp - current["min_xp"]
        tier_range = next_tier["min_xp"] - current["min_xp"]
        pct = min(100, round(tier_xp / tier_range * 100))
    else:
        tier_xp = xp - current["min_xp"]
        tier_range = 0
        pct = 100
    return {
        "current_tier": current,
        "next_tier": next_tier,
        "xp_in_tier": tier_xp,
        "xp_to_next": (next_tier["min_xp"] - xp) if next_tier else 0,
        "tier_range": tier_range,
        "progress_pct": pct,
    }


@router.get("/me")
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    xp = current_user.xp_total or 0
    unlocked = set(current_user.achievements or [])

    # Recent XP transactions
    txn_result = await db.execute(
        text("""
            SELECT amount, source_type, description, created_at
            FROM xp_transactions
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 10
        """),
        {"uid": current_user.id}
    )
    recent_xp = [
        {
            "amount": r.amount,
            "source_type": r.source_type,
            "description": r.description,
            "created_at": r.created_at.isoformat(),
        }
        for r in txn_result.fetchall()
    ]

    # Build achievements list (all, with unlocked flag)
    achievements_list = [
        {
            "key": key,
            "title": a["title"],
            "desc": a["desc"],
            "icon": a["icon"],
            "xp_bonus": a["xp"],
            "unlocked": key in unlocked,
        }
        for key, a in ACHIEVEMENTS.items()
    ]

    # Session stats
    stats_result = await db.execute(
        text("""
            SELECT COUNT(*) as total_sessions,
                   AVG(s.team_score) as avg_score
            FROM simulation_sessions s
            JOIN session_participants sp ON sp.session_id = s.id
            WHERE sp.user_id = :uid AND s.status = 'completed'
        """),
        {"uid": current_user.id}
    )
    stats_row = stats_result.fetchone()

    # Global rank by XP
    rank_result = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE xp_total > :xp AND is_active = true"),
        {"xp": xp}
    )
    global_rank = (rank_result.scalar() or 0) + 1

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "xp_total": xp,
        "career_tier": compute_tier(xp),
        "tier_progress": _tier_progress(xp),
        "global_rank": global_rank,
        "achievements": achievements_list,
        "unlocked_count": len(unlocked),
        "total_achievements": len(ACHIEVEMENTS),
        "recent_xp": recent_xp,
        "stats": {
            "total_sessions": stats_row.total_sessions if stats_row else 0,
            "avg_score": round(stats_row.avg_score or 0, 1) if stats_row else 0,
        },
        "member_since": current_user.created_at.isoformat(),
    }


@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Public leaderboard — top players by XP."""
    result = await db.execute(
        select(
            User.id, User.full_name, User.email,
            User.xp_total, User.career_tier, User.achievements,
        )
        .where(User.is_active == True)
        .order_by(desc(User.xp_total))
        .limit(limit)
    )
    rows = result.fetchall()
    return [
        {
            "rank": i + 1,
            "user_id": r.id,
            "display_name": r.full_name or r.email.split("@")[0],
            "xp_total": r.xp_total or 0,
            "career_tier": CAREER_TIERS[0] if not r.career_tier else
                           next((t for t in CAREER_TIERS if t["key"] == r.career_tier), CAREER_TIERS[0]),
            "achievements_count": len(r.achievements or []),
        }
        for i, r in enumerate(rows)
    ]


@router.get("/tiers")
async def get_career_tiers():
    """Return all career tiers — public endpoint for UI rendering."""
    return CAREER_TIERS


@router.get("/achievements")
async def get_all_achievements():
    """Return full achievements catalogue — public."""
    return [
        {"key": k, **v}
        for k, v in ACHIEVEMENTS.items()
    ]


# ── Live Breach Events Phase 1: public-profile opt-in ──────────────────────
#
# Opt-in only: full_name may already be a real name pulled in via OAuth, and
# must never appear on a public replay page (GET /arena/public/replay/{token})
# unless the user has explicitly enabled arena_profile_public AND set a handle.

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


class PublicProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_display_handle: str | None = Field(default=None)
    arena_profile_public: bool | None = Field(default=None)

    @field_validator("public_display_handle")
    @classmethod
    def _validate_handle(cls, v: str | None) -> str | None:
        if v is not None and not _HANDLE_RE.match(v):
            raise ValueError(
                "public_display_handle must be 3-20 characters, letters/digits/underscore only"
            )
        return v


@users_router.get("/me/public-profile")
async def get_public_profile(
    current_user: User = Depends(get_current_user),
):
    """Read-only hydration for the opt-in public-profile settings — same
    shape the PATCH below returns. No side effects."""
    return {
        "public_display_handle": current_user.public_display_handle,
        "arena_profile_public": current_user.arena_profile_public,
    }


@users_router.patch("/me/public-profile")
async def update_public_profile(
    payload: PublicProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the opt-in public display handle and/or public-profile toggle used
    by public Arena replay links. Uniqueness is pre-checked (same convention
    as email uniqueness at registration in auth.py's `register`) as a fast
    path, but two requests can race between that pre-check and commit — the
    `IntegrityError` handler below is the actual guarantee, catching the
    loser of that race and turning it into the same clean 409 rather than an
    unhandled 500."""
    if payload.public_display_handle is not None:
        existing = await db.execute(
            select(User).where(
                User.public_display_handle == payload.public_display_handle,
                User.id != current_user.id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="This display handle is already taken")
        current_user.public_display_handle = payload.public_display_handle

    if payload.arena_profile_public is not None:
        current_user.arena_profile_public = payload.arena_profile_public

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This display handle is already taken")
    await db.refresh(current_user)
    return {
        "public_display_handle": current_user.public_display_handle,
        "arena_profile_public": current_user.arena_profile_public,
    }
