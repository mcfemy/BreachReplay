"""
XP & Career Progression Service.
Awards XP, advances career tiers, and unlocks achievements.
"""
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.user import User
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Career tiers ───────────────────────────────────────────────────────────────

CAREER_TIERS = [
    {"key": "recruit",            "label": "Recruit",             "min_xp": 0,       "color": "#6b7280"},
    {"key": "soc_analyst",        "label": "SOC Analyst",         "min_xp": 1_000,   "color": "#3b82f6"},
    {"key": "incident_responder", "label": "Incident Responder",  "min_xp": 5_000,   "color": "#8b5cf6"},
    {"key": "threat_hunter",      "label": "Threat Hunter",       "min_xp": 15_000,  "color": "#f59e0b"},
    {"key": "security_architect", "label": "Security Architect",  "min_xp": 40_000,  "color": "#ef4444"},
    {"key": "ciso",               "label": "CISO",                "min_xp": 100_000, "color": "#ec4899"},
]

TIER_BY_KEY = {t["key"]: t for t in CAREER_TIERS}

# ── Achievements catalogue ─────────────────────────────────────────────────────

ACHIEVEMENTS = {
    # Scenario milestones
    "first_blood":        {"title": "First Blood",        "desc": "Complete your first scenario",                     "icon": "🩸", "xp": 100},
    "perfect_analyst":    {"title": "Perfect Analyst",    "desc": "Score 100% on any scenario",                       "icon": "💯", "xp": 200},
    "speed_demon":        {"title": "Speed Demon",        "desc": "Complete a scenario in under 5 minutes",           "icon": "⚡", "xp": 150},
    "scenario_5":         {"title": "Case File: 5",       "desc": "Complete 5 different scenarios",                   "icon": "📁", "xp": 250},
    "scenario_10":        {"title": "Case File: 10",      "desc": "Complete 10 different scenarios",                  "icon": "🗂️", "xp": 500},
    # Daily Breach milestones
    "daily_3":            {"title": "3-Day Streak",       "desc": "Play Daily Breach 3 days in a row",                "icon": "🔥", "xp": 75},
    "daily_7":            {"title": "Week Warrior",       "desc": "Play Daily Breach 7 days in a row",                "icon": "🔥", "xp": 200},
    "daily_30":           {"title": "Monthly Threat",     "desc": "Play Daily Breach 30 days in a row",               "icon": "🏅", "xp": 1_000},
    "daily_perfect":      {"title": "Perfect Day",        "desc": "Score 1,250 points in Daily Breach",               "icon": "🎯", "xp": 300},
    # Red Team milestones
    "red_rookie":         {"title": "Red Rookie",         "desc": "Complete your first Red Team operation",           "icon": "🔴", "xp": 150},
    "ghost_protocol":     {"title": "Ghost Protocol",     "desc": "Complete Red Team with stealth above 80",          "icon": "👻", "xp": 300},
    "devastating_impact": {"title": "Devastating Impact", "desc": "Reach impact 90+ in Red Team mode",                "icon": "💥", "xp": 300},
    "red_master":         {"title": "Red Master",         "desc": "Complete 5 Red Team operations",                   "icon": "🎖️", "xp": 500},
    # XP milestones
    "xp_1k":              {"title": "Rising Threat",      "desc": "Earn 1,000 total XP",                              "icon": "⭐", "xp": 0},
    "xp_10k":             {"title": "Elite Operator",     "desc": "Earn 10,000 total XP",                             "icon": "🌟", "xp": 0},
    "xp_50k":             {"title": "Cyber Legend",       "desc": "Earn 50,000 total XP",                             "icon": "🏆", "xp": 0},
    # Scenario-specific badges
    "colonial_veteran":   {"title": "Colonial Veteran",   "desc": "Complete the Colonial Pipeline scenario",          "icon": "🛢️", "xp": 100},
    "log4shell_expert":   {"title": "Log4Shell Expert",   "desc": "Complete the Log4Shell scenario",                  "icon": "☕", "xp": 100},
    "solarwinds_hunter":  {"title": "SolarWinds Hunter",  "desc": "Complete the SolarWinds scenario",                 "icon": "🌐", "xp": 100},
}


def compute_tier(xp: int) -> dict:
    """Return the career tier dict for a given XP total."""
    current = CAREER_TIERS[0]
    for tier in CAREER_TIERS:
        if xp >= tier["min_xp"]:
            current = tier
    return current


def xp_to_next_tier(xp: int) -> Optional[int]:
    """XP needed to reach the next tier. None if at max."""
    for i, tier in enumerate(CAREER_TIERS):
        if xp < tier["min_xp"]:
            return tier["min_xp"] - xp
    return None


async def award_xp(
    db: AsyncSession,
    user_id: str,
    amount: int,
    source_type: str,
    description: str,
    source_id: Optional[str] = None,
) -> dict:
    """
    Award XP to a user. Returns a summary dict with old_tier, new_tier, leveled_up, and new_achievements.
    """
    from app.models.user import User

    if amount <= 0:
        return {"amount": 0, "leveled_up": False, "new_achievements": []}

    # Load current user state
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"amount": 0, "leveled_up": False, "new_achievements": []}

    old_xp = user.xp_total or 0
    old_tier = compute_tier(old_xp)
    new_xp = old_xp + amount
    new_tier = compute_tier(new_xp)
    leveled_up = new_tier["key"] != old_tier["key"]

    # Log XP transaction
    from sqlalchemy import text
    tx_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO xp_transactions (id, user_id, amount, source_type, source_id, description, created_at)
            VALUES (:id, :user_id, :amount, :source_type, :source_id, :description, :created_at)
        """),
        {
            "id": tx_id,
            "user_id": user_id,
            "amount": amount,
            "source_type": source_type,
            "source_id": source_id,
            "description": description,
            "created_at": datetime.utcnow(),
        }
    )

    # Update user XP and tier
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(xp_total=new_xp, career_tier=new_tier["key"])
    )

    await db.commit()

    logger.info("Awarded %d XP to user %s (%s). Total: %d", amount, user_id, source_type, new_xp)

    return {
        "amount": amount,
        "new_xp": new_xp,
        "old_tier": old_tier,
        "new_tier": new_tier,
        "leveled_up": leveled_up,
        "new_achievements": [],
    }


async def unlock_achievement(db: AsyncSession, user_id: str, key: str) -> bool:
    """Unlock an achievement for a user. Returns True if newly unlocked."""
    if key not in ACHIEVEMENTS:
        return False

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False

    current = list(user.achievements or [])
    if key in current:
        return False

    current.append(key)

    from sqlalchemy import text
    await db.execute(
        text("UPDATE users SET achievements = :a::jsonb WHERE id = :id"),
        {"a": __import__("json").dumps(current), "id": user_id}
    )

    # Award XP bonus for achievement
    bonus = ACHIEVEMENTS[key].get("xp", 0)
    if bonus > 0:
        await award_xp(
            db, user_id, bonus, "achievement",
            f"Achievement unlocked: {ACHIEVEMENTS[key]['title']}",
            source_id=key,
        )
    else:
        await db.commit()

    logger.info("Achievement '%s' unlocked for user %s", key, user_id)
    return True


async def check_scenario_achievements(
    db: AsyncSession,
    user_id: str,
    scenario_title: str,
    score_pct: float,
    time_seconds: int,
    total_completed: int,
) -> list[str]:
    """Check and unlock scenario-related achievements. Returns list of newly unlocked keys."""
    unlocked = []

    if total_completed == 1:
        if await unlock_achievement(db, user_id, "first_blood"):
            unlocked.append("first_blood")

    if score_pct >= 100:
        if await unlock_achievement(db, user_id, "perfect_analyst"):
            unlocked.append("perfect_analyst")

    if time_seconds <= 300:
        if await unlock_achievement(db, user_id, "speed_demon"):
            unlocked.append("speed_demon")

    if total_completed >= 5:
        if await unlock_achievement(db, user_id, "scenario_5"):
            unlocked.append("scenario_5")

    if total_completed >= 10:
        if await unlock_achievement(db, user_id, "scenario_10"):
            unlocked.append("scenario_10")

    title_lower = scenario_title.lower()
    if "colonial" in title_lower:
        if await unlock_achievement(db, user_id, "colonial_veteran"):
            unlocked.append("colonial_veteran")
    if "log4shell" in title_lower or "log4j" in title_lower:
        if await unlock_achievement(db, user_id, "log4shell_expert"):
            unlocked.append("log4shell_expert")
    if "solarwinds" in title_lower:
        if await unlock_achievement(db, user_id, "solarwinds_hunter"):
            unlocked.append("solarwinds_hunter")

    return unlocked


async def check_daily_achievements(
    db: AsyncSession,
    user_id: str,
    streak: int,
    score: int,
) -> list[str]:
    unlocked = []
    if streak >= 3:
        if await unlock_achievement(db, user_id, "daily_3"):
            unlocked.append("daily_3")
    if streak >= 7:
        if await unlock_achievement(db, user_id, "daily_7"):
            unlocked.append("daily_7")
    if streak >= 30:
        if await unlock_achievement(db, user_id, "daily_30"):
            unlocked.append("daily_30")
    if score >= 1250:
        if await unlock_achievement(db, user_id, "daily_perfect"):
            unlocked.append("daily_perfect")
    return unlocked


async def check_redteam_achievements(
    db: AsyncSession,
    user_id: str,
    stealth: int,
    impact: int,
    total_operations: int,
) -> list[str]:
    unlocked = []
    if total_operations == 1:
        if await unlock_achievement(db, user_id, "red_rookie"):
            unlocked.append("red_rookie")
    if stealth >= 80:
        if await unlock_achievement(db, user_id, "ghost_protocol"):
            unlocked.append("ghost_protocol")
    if impact >= 90:
        if await unlock_achievement(db, user_id, "devastating_impact"):
            unlocked.append("devastating_impact")
    if total_operations >= 5:
        if await unlock_achievement(db, user_id, "red_master"):
            unlocked.append("red_master")
    return unlocked


async def check_xp_milestones(db: AsyncSession, user_id: str, new_xp: int) -> list[str]:
    unlocked = []
    if new_xp >= 1_000:
        if await unlock_achievement(db, user_id, "xp_1k"):
            unlocked.append("xp_1k")
    if new_xp >= 10_000:
        if await unlock_achievement(db, user_id, "xp_10k"):
            unlocked.append("xp_10k")
    if new_xp >= 50_000:
        if await unlock_achievement(db, user_id, "xp_50k"):
            unlocked.append("xp_50k")
    return unlocked
