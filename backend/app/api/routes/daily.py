"""
Daily Breach — the Wordle of cybersecurity.
One scenario per day, global leaderboard, streaks, share cards.
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, desc
from pydantic import BaseModel

from app.db.session import get_db
from app.models.daily_challenge import DailyChallenge, DailyAttempt, UserStreak
from app.models.scenario import Scenario
from app.models.user import User
from app.core.security import get_current_user
from app.core.logging import get_logger
from app.services import xp_service

router = APIRouter(prefix="/daily", tags=["daily"])
logger = get_logger(__name__)

DAILY_GATE_LIMIT = 6          # max gates shown in daily mode
DAILY_TIME_LIMIT_SECONDS = 600  # 10 minutes hard cap


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class DecisionEntry(BaseModel):
    gate_id: str
    chosen_index: int
    correct_index: int
    is_correct: bool
    response_time_seconds: float


class DailyAttemptSubmit(BaseModel):
    daily_challenge_id: str
    decisions: list[DecisionEntry]
    time_taken_seconds: int


class DailyChallengeOut(BaseModel):
    id: str
    challenge_date: str
    challenge_number: int
    scenario_id: str
    scenario_title: str
    scenario_difficulty: str
    scenario_industry: Optional[str]
    initial_access_vector: Optional[str]
    gates_count: int
    total_attempts: int
    already_played: bool
    my_attempt: Optional[dict] = None


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    display_name: str
    score: int
    decisions_correct: int
    decisions_total: int
    time_taken_seconds: Optional[int]


class StreakOut(BaseModel):
    current_streak: int
    longest_streak: int
    total_dailies_played: int
    last_played_date: Optional[str]
    played_today: bool


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_score(decisions: list[DecisionEntry], time_taken: int) -> int:
    """
    Scoring formula:
    - Base: 100 pts per correct decision
    - Speed bonus: up to 50 pts per gate based on response time (< 10s = full, < 30s = half)
    - Clutch bonus: +150 if last gate is correct under 8 seconds
    - Perfection bonus: +200 if all correct
    Max theoretical: 6×100 + 6×50 + 150 + 200 = 1250
    """
    total = 0
    for d in decisions:
        if d.is_correct:
            total += 100
            if d.response_time_seconds <= 10:
                total += 50
            elif d.response_time_seconds <= 30:
                total += 25

    # Clutch: last gate correct under 8s
    if decisions and decisions[-1].is_correct and decisions[-1].response_time_seconds <= 8:
        total += 150

    # Perfection
    if all(d.is_correct for d in decisions):
        total += 200

    return total


def _build_share_card(
    challenge_number: int,
    scenario_title: str,
    decisions: list[DecisionEntry],
    score: int,
    streak: int,
) -> str:
    """Build Wordle-style shareable text."""
    emojis = "".join("✅" if d.is_correct else "❌" for d in decisions)
    correct = sum(1 for d in decisions if d.is_correct)
    streak_txt = f"🔥 {streak}-day streak" if streak > 1 else ""
    return (
        f"🔐 BreachReplay Daily #{challenge_number}\n"
        f"{scenario_title}\n"
        f"Score: {score:,} | {correct}/{len(decisions)} correct\n"
        f"{emojis}\n"
        f"{streak_txt}\n"
        f"breachreplay.com/daily"
    ).strip()


async def _get_or_create_streak(db: AsyncSession, user_id: str) -> UserStreak:
    result = await db.execute(select(UserStreak).where(UserStreak.user_id == user_id))
    streak = result.scalar_one_or_none()
    if not streak:
        streak = UserStreak(
            user_id=user_id,
            current_streak=0,
            longest_streak=0,
            total_dailies_played=0,
            updated_at=datetime.utcnow(),
        )
        db.add(streak)
        await db.flush()
    return streak


async def _update_streak(db: AsyncSession, streak: UserStreak) -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)

    if streak.last_played_date == today:
        return  # already played today, no update needed

    if streak.last_played_date == yesterday:
        streak.current_streak += 1
    else:
        streak.current_streak = 1  # streak broken or first play

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak

    streak.last_played_date = today
    streak.total_dailies_played += 1
    streak.updated_at = datetime.utcnow()


async def _recalculate_ranks(db: AsyncSession, challenge_id: str) -> None:
    """Recompute rank for all attempts on this challenge, ordered by score desc then time asc."""
    result = await db.execute(
        select(DailyAttempt)
        .where(DailyAttempt.daily_challenge_id == challenge_id)
        .order_by(desc(DailyAttempt.score), DailyAttempt.time_taken_seconds)
    )
    attempts = result.scalars().all()
    for rank, attempt in enumerate(attempts, start=1):
        attempt.rank = rank


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/today", response_model=DailyChallengeOut)
async def get_today_challenge(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return today's Daily Breach challenge with metadata."""
    today = date.today()

    result = await db.execute(
        select(DailyChallenge).where(DailyChallenge.challenge_date == today)
    )
    challenge = result.scalar_one_or_none()

    if not challenge:
        # Auto-assign today's challenge: pick a random approved scenario
        sc_result = await db.execute(
            select(Scenario)
            .where(Scenario.status == "approved")
            .order_by(func.random())
            .limit(1)
        )
        scenario = sc_result.scalar_one_or_none()
        if not scenario:
            raise HTTPException(status_code=404, detail="No approved scenarios available for today's challenge")

        # Get next challenge number
        num_result = await db.execute(select(func.count()).select_from(DailyChallenge))
        count = num_result.scalar() or 0

        challenge = DailyChallenge(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            challenge_date=today,
            challenge_number=count + 1,
            created_at=datetime.utcnow(),
        )
        db.add(challenge)
        await db.commit()
        await db.refresh(challenge)

    # Load scenario
    sc_result = await db.execute(select(Scenario).where(Scenario.id == challenge.scenario_id))
    scenario = sc_result.scalar_one()

    # Check if current user already played
    attempt_result = await db.execute(
        select(DailyAttempt).where(
            DailyAttempt.daily_challenge_id == challenge.id,
            DailyAttempt.user_id == current_user.id,
        )
    )
    my_attempt = attempt_result.scalar_one_or_none()

    my_attempt_data = None
    if my_attempt:
        share_card = _build_share_card(
            challenge_number=challenge.challenge_number,
            scenario_title=scenario.title,
            decisions=[DecisionEntry(**d) for d in (my_attempt.decision_log or [])],
            score=my_attempt.score,
            streak=0,
        )
        my_attempt_data = {
            "score": my_attempt.score,
            "rank": my_attempt.rank,
            "decisions_correct": my_attempt.decisions_correct,
            "decisions_total": my_attempt.decisions_total,
            "time_taken_seconds": my_attempt.time_taken_seconds,
            "share_card": share_card,
        }

    gates = scenario.decision_tree or []

    return DailyChallengeOut(
        id=challenge.id,
        challenge_date=today.isoformat(),
        challenge_number=challenge.challenge_number,
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        scenario_difficulty=scenario.difficulty or "practitioner",
        scenario_industry=scenario.industry_vertical,
        initial_access_vector=scenario.initial_access_vector,
        gates_count=min(len(gates), DAILY_GATE_LIMIT),
        total_attempts=challenge.total_attempts,
        already_played=my_attempt is not None,
        my_attempt=my_attempt_data,
    )


@router.get("/scenario/{challenge_id}")
async def get_daily_scenario_content(
    challenge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the actual scenario content (gates + alerts) for the daily challenge.
    Capped at DAILY_GATE_LIMIT gates and first 15 alerts.
    Only callable once — if user already has an attempt, returns 409."""
    result = await db.execute(select(DailyChallenge).where(DailyChallenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Daily challenge not found")

    # Check already played
    attempt_result = await db.execute(
        select(DailyAttempt).where(
            DailyAttempt.daily_challenge_id == challenge_id,
            DailyAttempt.user_id == current_user.id,
        )
    )
    if attempt_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already played today's breach")

    sc_result = await db.execute(select(Scenario).where(Scenario.id == challenge.scenario_id))
    scenario = sc_result.scalar_one()

    gates = (scenario.decision_tree or [])[:DAILY_GATE_LIMIT]
    alerts = (scenario.alert_sequence or [])[:15]
    pressures = (scenario.pressure_injections or [])[:3]

    return {
        "challenge_id": challenge_id,
        "challenge_number": challenge.challenge_number,
        "scenario_id": scenario.id,
        "title": scenario.title,
        "difficulty": scenario.difficulty,
        "industry_vertical": scenario.industry_vertical,
        "initial_access_vector": scenario.initial_access_vector,
        "time_limit_seconds": DAILY_TIME_LIMIT_SECONDS,
        "alert_sequence": alerts,
        "decision_tree": gates,
        "pressure_injections": pressures,
        "mitre_techniques": scenario.mitre_techniques or [],
        "nist_controls": scenario.nist_controls or [],
    }


@router.post("/attempt", status_code=status.HTTP_201_CREATED)
async def submit_attempt(
    payload: DailyAttemptSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit the player's decisions for today's breach. One attempt per day."""
    result = await db.execute(
        select(DailyChallenge).where(DailyChallenge.id == payload.daily_challenge_id)
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Daily challenge not found")

    # Enforce one attempt per day
    existing = await db.execute(
        select(DailyAttempt).where(
            DailyAttempt.daily_challenge_id == payload.daily_challenge_id,
            DailyAttempt.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You've already submitted today's breach")

    # Enforce time cap
    time_taken = min(payload.time_taken_seconds, DAILY_TIME_LIMIT_SECONDS)

    score = _compute_score(payload.decisions, time_taken)
    correct = sum(1 for d in payload.decisions if d.is_correct)

    attempt = DailyAttempt(
        id=str(uuid.uuid4()),
        daily_challenge_id=payload.daily_challenge_id,
        user_id=current_user.id,
        score=score,
        decisions_correct=correct,
        decisions_total=len(payload.decisions),
        decision_log=[d.model_dump() for d in payload.decisions],
        time_taken_seconds=time_taken,
        completed_at=datetime.utcnow(),
    )
    db.add(attempt)

    # Update challenge aggregate stats
    challenge.total_attempts += 1
    if challenge.avg_score is None:
        challenge.avg_score = float(score)
    else:
        # Running average
        challenge.avg_score = (
            (challenge.avg_score * (challenge.total_attempts - 1) + score)
            / challenge.total_attempts
        )

    await db.flush()

    # Recompute ranks for all attempts on this challenge
    await _recalculate_ranks(db, payload.daily_challenge_id)

    # Update streak
    streak = await _get_or_create_streak(db, current_user.id)
    await _update_streak(db, streak)
    await db.commit()
    await db.refresh(attempt)

    # Award XP: base score/3 + streak bonus
    xp_amount = max(10, score // 3) + (streak.current_streak * 5)
    xp_result = await xp_service.award_xp(
        db, current_user.id, xp_amount, "daily",
        f"Daily Breach #{challenge.challenge_number} — {correct}/{len(payload.decisions)} correct, {score:,} pts",
        source_id=attempt.id,
    )
    achievement_keys = await xp_service.check_daily_achievements(
        db, current_user.id, streak.current_streak, score
    )
    achievement_keys += await xp_service.check_xp_milestones(db, current_user.id, xp_result.get("new_xp", 0))

    # Load scenario title for share card
    sc_result = await db.execute(select(Scenario).where(Scenario.id == challenge.scenario_id))
    scenario = sc_result.scalar_one()

    share_card = _build_share_card(
        challenge_number=challenge.challenge_number,
        scenario_title=scenario.title,
        decisions=payload.decisions,
        score=score,
        streak=streak.current_streak,
    )

    return {
        "score": score,
        "rank": attempt.rank,
        "decisions_correct": correct,
        "decisions_total": len(payload.decisions),
        "time_taken_seconds": time_taken,
        "current_streak": streak.current_streak,
        "longest_streak": streak.longest_streak,
        "total_dailies_played": streak.total_dailies_played,
        "share_card": share_card,
        "challenge_number": challenge.challenge_number,
        "total_attempts_today": challenge.total_attempts,
        "avg_score_today": round(challenge.avg_score or 0),
        "xp_earned": xp_amount,
        "new_achievements": achievement_keys,
        "leveled_up": xp_result.get("leveled_up", False),
        "new_tier": xp_result.get("new_tier"),
    }


@router.get("/leaderboard/{challenge_id}", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    challenge_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top players for a given daily challenge, ordered by score then speed."""
    result = await db.execute(
        select(DailyAttempt, User.full_name, User.email)
        .join(User, DailyAttempt.user_id == User.id)
        .where(DailyAttempt.daily_challenge_id == challenge_id)
        .order_by(desc(DailyAttempt.score), DailyAttempt.time_taken_seconds)
        .limit(limit)
    )
    rows = result.all()
    return [
        LeaderboardEntry(
            rank=attempt.rank or (i + 1),
            user_id=attempt.user_id,
            display_name=full_name or email.split("@")[0],
            score=attempt.score,
            decisions_correct=attempt.decisions_correct,
            decisions_total=attempt.decisions_total,
            time_taken_seconds=attempt.time_taken_seconds,
        )
        for i, (attempt, full_name, email) in enumerate(rows)
    ]


@router.get("/streak", response_model=StreakOut)
async def get_my_streak(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    streak = await _get_or_create_streak(db, current_user.id)
    today = date.today()
    played_today = streak.last_played_date == today
    return StreakOut(
        current_streak=streak.current_streak,
        longest_streak=streak.longest_streak,
        total_dailies_played=streak.total_dailies_played,
        last_played_date=streak.last_played_date.isoformat() if streak.last_played_date else None,
        played_today=played_today,
    )


@router.get("/history")
async def get_challenge_history(
    limit: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Last N daily challenges with user's result for each."""
    result = await db.execute(
        select(DailyChallenge)
        .order_by(desc(DailyChallenge.challenge_date))
        .limit(limit)
    )
    challenges = result.scalars().all()

    history = []
    for c in challenges:
        sc_result = await db.execute(select(Scenario.title).where(Scenario.id == c.scenario_id))
        title = sc_result.scalar_one_or_none() or "Unknown"

        attempt_result = await db.execute(
            select(DailyAttempt).where(
                DailyAttempt.daily_challenge_id == c.id,
                DailyAttempt.user_id == current_user.id,
            )
        )
        my = attempt_result.scalar_one_or_none()

        history.append({
            "challenge_number": c.challenge_number,
            "challenge_date": c.challenge_date.isoformat(),
            "scenario_title": title,
            "total_attempts": c.total_attempts,
            "avg_score": round(c.avg_score or 0),
            "my_score": my.score if my else None,
            "my_rank": my.rank if my else None,
            "played": my is not None,
        })

    return history
