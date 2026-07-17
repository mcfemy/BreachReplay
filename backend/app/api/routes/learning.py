"""
Knowledge checks + spaced repetition ("Daily Drill").
Optional/supplementary learning surface — does not gate the main decision-gate
flow. Selection weights toward the user's weakest techniques per
app.services.mastery_service.compute_user_mastery.
"""
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.user import User
from app.models.knowledge_check import KnowledgeCheck, UserKnowledgeCheckAttempt
from app.core.security import get_current_user
from app.services import mastery_service

router = APIRouter(prefix="/learning", tags=["learning"])


class AttemptRequest(BaseModel):
    chosen_index: int


@router.get("/knowledge-check/next")
async def get_next_knowledge_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    technique_mastery = await mastery_service.compute_user_mastery(db, current_user.id)

    weakest_techniques = sorted(
        (
            tid
            for tid, stats in technique_mastery.items()
            if stats["attempts"] >= 1
        ),
        key=lambda tid: technique_mastery[tid]["accuracy_pct"],
    )

    # compute_user_mastery is driven by SessionDecision/RedTeamMove history,
    # not by knowledge-check attempts (drilling a question doesn't change its
    # own technique's accuracy_pct) — so a user's weakest technique stays
    # exactly where it was before and after answering. Most seeded techniques
    # have exactly one KnowledgeCheck row, so without this exclusion "Next"
    # would hand back the very question just answered, every time, forever.
    # Excluding only the single most recent attempt is enough to break that:
    # it forces a different question (from this technique if it has more than
    # one, otherwise the next-weakest technique, or the fallback pool) without
    # blocking a question from legitimately resurfacing later, which spaced
    # repetition depends on.
    last_attempt_result = await db.execute(
        select(UserKnowledgeCheckAttempt.knowledge_check_id)
        .where(UserKnowledgeCheckAttempt.user_id == current_user.id)
        .order_by(UserKnowledgeCheckAttempt.created_at.desc())
        .limit(1)
    )
    excluded_ids = {row[0] for row in last_attempt_result.all()}

    question = None

    # Try weakest techniques first, in order of ascending accuracy.
    for technique_id in weakest_techniques:
        result = await db.execute(
            select(KnowledgeCheck).where(KnowledgeCheck.technique_id == technique_id)
        )
        candidates = [c for c in result.scalars().all() if c.id not in excluded_ids]
        if candidates:
            question = random.choice(candidates)
            break

    # Fallback: no mastery data yet, no question matches any weak technique,
    # or every candidate for the weakest technique(s) was just excluded.
    if question is None:
        result = await db.execute(select(KnowledgeCheck))
        all_checks = result.scalars().all()
        candidates = [c for c in all_checks if c.id not in excluded_ids]
        if not candidates:
            # Every question (including the excluded one) has been exhausted
            # — only possible with a single-question bank. Allow the repeat
            # rather than 404ing a user who legitimately has nothing else.
            candidates = all_checks
        if not candidates:
            raise HTTPException(status_code=404, detail="No knowledge checks available")
        question = random.choice(candidates)

    return {
        "id": question.id,
        "scenario_id": question.scenario_id,
        "technique_id": question.technique_id,
        "nist_control_ref": question.nist_control_ref,
        "question": question.question,
        "options": question.options,
    }


@router.post("/knowledge-check/{knowledge_check_id}/attempt")
async def submit_knowledge_check_attempt(
    knowledge_check_id: str,
    payload: AttemptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeCheck).where(KnowledgeCheck.id == knowledge_check_id)
    )
    check = result.scalar_one_or_none()
    if check is None:
        raise HTTPException(status_code=404, detail="Knowledge check not found")

    is_correct = payload.chosen_index == check.correct_index

    attempt = UserKnowledgeCheckAttempt(
        user_id=current_user.id,
        knowledge_check_id=check.id,
        chosen_index=payload.chosen_index,
        is_correct=is_correct,
    )
    db.add(attempt)
    await db.commit()

    return {
        "is_correct": is_correct,
        "correct_index": check.correct_index,
        "explanation": check.explanation,
    }
