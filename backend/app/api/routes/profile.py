"""
User profile, XP, achievements, and global leaderboard.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text

from app.db.session import get_db
from app.models.user import User
from app.core.security import get_current_user
from app.services.xp_service import CAREER_TIERS, ACHIEVEMENTS, compute_tier, xp_to_next_tier

router = APIRouter(prefix="/profile", tags=["profile"])


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
