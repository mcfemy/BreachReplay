"""
Phase 1 — No-auth landing teaser (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 3).

Anonymous, rate-limited, single-decision teaser: a first-time visitor plays a
60-second, one-decision slice of the Colonial Pipeline scenario with zero
auth. Every route here is public by design except /teaser/claim, which
requires a freshly-created/logged-in account to attach the anonymous result
to it. See teaser_data.py for why the payload is a hand-curated constant
rather than a live Scenario DB read — the whole point is that
hidden_iocs/decision_tree internals can never leak through this surface.

The signed anonymous token (`teaser_token`) is a short-lived (15 min) JWT
carrying only an opaque `tid` correlation id — deliberately NOT built with
create_access_token/decode_token (app.core.security), which assume `sub`
resolves to a real users.id row. Mixing the two token families would let a
teaser token be replayed against real authenticated routes, or vice versa.
"""
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt as jose_jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, limiter
from app.db.session import get_db
from app.models.teaser_event import TeaserEvent
from app.models.user import User
from app.services import teaser_data
from app.services.xp_service import unlock_achievement

router = APIRouter(prefix="/teaser", tags=["teaser"])

_TEASER_TOKEN_TYP = "teaser"
_TEASER_TOKEN_TTL_MINUTES = 15


def _create_teaser_token(token_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=_TEASER_TOKEN_TTL_MINUTES)
    return jose_jwt.encode(
        {"typ": _TEASER_TOKEN_TYP, "tid": token_id, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _verify_teaser_token(token: str) -> str:
    try:
        payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired teaser token")
    if payload.get("typ") != _TEASER_TOKEN_TYP or not payload.get("tid"):
        raise HTTPException(status_code=401, detail="Invalid teaser token")
    return payload["tid"]


class TeaserAnswerRequest(BaseModel):
    teaser_token: str
    chosen_node_id: str


class TeaserClaimRequest(BaseModel):
    teaser_token: str


@router.post("/start")
@limiter.limit("20/minute")
async def start_teaser(request: Request, db: AsyncSession = Depends(get_db)):
    token_id = str(uuid.uuid4())
    db.add(TeaserEvent(
        event_type="teaser_started",
        token_id=token_id,
        scenario_key=teaser_data.SCENARIO_KEY,
        created_at=datetime.utcnow(),
    ))
    await db.commit()

    return {
        "teaser_token": _create_teaser_token(token_id),
        "scenario_key": teaser_data.SCENARIO_KEY,
        "headline": teaser_data.HEADLINE,
        "countdown_seconds": teaser_data.COUNTDOWN_SECONDS,
        "nodes": teaser_data.NODES,
        "edges": teaser_data.EDGES,
        "node_states": teaser_data.INITIAL_NODE_STATES,
        "alert_lines": teaser_data.ALERT_LINES,
        "decision": teaser_data.DECISION,
    }


def _build_answer_response(correct: bool) -> dict:
    """Deterministic answer payload for a given outcome. Shared by the fresh
    path and the first-answer-wins replay path so a repeated /answer call
    reconstructs the exact same body from the stored outcome."""
    if correct:
        node_states = {teaser_data.TEASER_CORRECT_NODE_ID: "contained"}
        consequence_text = teaser_data.CONSEQUENCE_CORRECT
    else:
        node_states = {teaser_data.TEASER_CORRECT_NODE_ID: "compromised"}
        for node_id in teaser_data.CONSEQUENCE_WRONG_BLEED_NODES:
            node_states[node_id] = "compromised"
        consequence_text = teaser_data.CONSEQUENCE_WRONG

    return {
        "correct": correct,
        "node_states": node_states,
        "consequence_text": consequence_text,
        "end_card_text": teaser_data.END_CARD_TEXT,
    }


@router.post("/answer")
@limiter.limit("20/minute")
async def answer_teaser(request: Request, payload: TeaserAnswerRequest, db: AsyncSession = Depends(get_db)):
    token_id = _verify_teaser_token(payload.teaser_token)

    # First-answer-wins. If this token already recorded a decision, return that
    # original outcome and write nothing. This blocks two abuses: (1) re-calling
    # with a different node to "correct" a wrong pick, and (2) stacking
    # duplicate decided/completed rows that would inflate the funnel counts.
    # The incoming chosen_node_id is deliberately ignored on a replay, so the
    # answer can't be revised after the fact.
    prior_decided = await db.execute(
        select(TeaserEvent)
        .where(TeaserEvent.token_id == token_id, TeaserEvent.event_type == "teaser_decided")
        .limit(1)
    )
    prior = prior_decided.scalar_one_or_none()
    if prior is not None:
        return _build_answer_response(prior.outcome == "correct")

    if payload.chosen_node_id not in teaser_data.DECISION["node_choices"]:
        raise HTTPException(status_code=400, detail="Invalid node choice")

    correct = payload.chosen_node_id == teaser_data.TEASER_CORRECT_NODE_ID
    outcome = "correct" if correct else "wrong"
    now = datetime.utcnow()
    # "decided" and "completed" both fire off this single call — a teaser
    # has exactly one decision gate, so the moment it's answered is also the
    # moment the run completes (immediate consequence, then the end card).
    db.add(TeaserEvent(event_type="teaser_decided", token_id=token_id,
                        scenario_key=teaser_data.SCENARIO_KEY, outcome=outcome, created_at=now))
    db.add(TeaserEvent(event_type="teaser_completed", token_id=token_id,
                        scenario_key=teaser_data.SCENARIO_KEY, outcome=outcome, created_at=now))
    await db.commit()

    return _build_answer_response(correct)


@router.post("/claim")
@limiter.limit("10/minute")
async def claim_teaser(
    request: Request,
    payload: TeaserClaimRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Attach a just-completed anonymous teaser result to a freshly
    authenticated account (Conversion continuity, spec section 3). Requires
    the caller to already be authenticated — called by the frontend right
    after register/login/OAuth callback if a teaser_token is sitting in
    sessionStorage. Idempotent: claiming twice with the same token just
    unlocks the achievement once (unlock_achievement itself no-ops on an
    already-unlocked key)."""
    token_id = _verify_teaser_token(payload.teaser_token)

    result = await db.execute(
        select(TeaserEvent)
        .where(TeaserEvent.token_id == token_id, TeaserEvent.event_type == "teaser_completed")
        .order_by(TeaserEvent.created_at.desc())
        .limit(1)
    )
    completed_event = result.scalar_one_or_none()
    if completed_event is None:
        raise HTTPException(status_code=404, detail="No completed teaser run for this token")

    achievement_unlocked = await unlock_achievement(db, current_user.id, "teaser_survivor")

    db.add(TeaserEvent(
        event_type="signup_from_teaser",
        token_id=token_id,
        scenario_key=teaser_data.SCENARIO_KEY,
        outcome=completed_event.outcome,
        user_id=current_user.id,
        created_at=datetime.utcnow(),
    ))
    await db.commit()

    return {"claimed": True, "achievement_unlocked": achievement_unlocked}
