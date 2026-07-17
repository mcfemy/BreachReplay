"""
Tests for backend/app/api/routes/learning.py's `/learning/knowledge-check/*`
routes (the "Daily Drill" spaced-repetition widget on DailyBreachPage.tsx).

Regression coverage for a production bug report: answering a drill question
and clicking "Next" re-displayed the exact same question instead of
advancing. Root cause, confirmed by reading `mastery_service.compute_user_mastery`
directly: it aggregates `SessionDecision`/`RedTeamMove` history only — a
`UserKnowledgeCheckAttempt` never changes a technique's `accuracy_pct`. So a
user's weakest technique (the one `get_next_knowledge_check` targets) stays
exactly where it was before and after drilling it. Combined with the seed
data (`backend/seed.py`), 10 of 11 real techniques have exactly one
`KnowledgeCheck` row — so without an exclusion guard, "Next" was guaranteed
to hand back the very question just answered, every time, for any user who
already had decision-gate/red-team play history establishing a weakest
technique. This is a different bug shape than the `/teaser/answer`
idempotency bug (`docs/PHASE1_ANSWER_IDEMPOTENCY_HANDOFF.md`) — that one was
a missing re-submission guard on a write endpoint; this one is a missing
repeat-exclusion on a read/selection endpoint. No fix here touches
`mastery_service.py` itself — it has other callers (`admin.py`, `mastery.py`,
`cert_service.py`) that must keep meaning what they already mean.
"""
import pytest
from sqlalchemy import select

from app.models.knowledge_check import KnowledgeCheck, UserKnowledgeCheckAttempt
from app.models.session import SessionDecision, SimulationSession

pytestmark = pytest.mark.asyncio


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_weak_technique(db, user, approved_scenario, technique_id: str, correct: bool = False) -> None:
    """Gives the user real SessionDecision history for `technique_id`, the
    same signal compute_user_mastery reads — establishing it as a real
    "weakest technique" rather than an empty-mastery fallback case."""
    session = SimulationSession(
        scenario_id=approved_scenario.id,
        host_user_id=user.id,
        status="completed",
    )
    db.add(session)
    await db.flush()
    db.add(SessionDecision(
        session_id=session.id,
        user_id=user.id,
        decision_gate_id="gate-001",
        chosen_option_index=0,
        is_correct=correct,
        mitre_technique=technique_id,
    ))
    await db.commit()


async def test_next_does_not_immediately_repeat_the_just_answered_question(client, db, test_user, approved_scenario):
    """The exact reported bug: a technique with only ONE candidate question
    (the common case per seed.py) must not be served twice in a row after
    being answered. Before the fix, this looped forever on the same id."""
    solo = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-SOLO",
        question="Solo question", options=["a", "b"], correct_index=0, explanation="because",
    )
    other = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-OTHER",
        question="Other question", options=["a", "b"], correct_index=0, explanation="because",
    )
    db.add_all([solo, other])
    await db.commit()

    await _make_weak_technique(db, test_user["user"], approved_scenario, "T-SOLO")

    first = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
    assert first.status_code == 200
    assert first.json()["id"] == solo.id, "T-SOLO is the only technique with history — its sole question must be served first"

    attempt = await client.post(
        f"/api/v1/learning/knowledge-check/{solo.id}/attempt",
        headers=_auth_headers(test_user["token"]),
        json={"chosen_index": 1},
    )
    assert attempt.status_code == 200

    second = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
    assert second.status_code == 200
    assert second.json()["id"] != solo.id, (
        "answering T-SOLO's only question did not change T-SOLO's accuracy_pct "
        "(knowledge-check attempts don't feed mastery) — without the exclusion "
        "guard this would deterministically repeat the same question"
    )


async def test_next_excludes_only_the_just_answered_question_within_the_same_technique(client, db, test_user, approved_scenario):
    """When the weakest technique has more than one candidate, the exclusion
    must be precise — the other question in that same technique should still
    be preferred over falling through to a different (less weak) technique.

    With only 2 candidates, a single next->attempt->next round trip has a 50%
    chance of not repeating by pure luck even on the old, unfixed code
    (random.choice happens to pick the other one) — that would make a
    single-round-trip version of this test an unreliable regression guard.
    Repeating the round trip 20 times drives the false-pass probability on
    unfixed code down to 0.5**20, while the fixed code passes deterministically
    every time regardless of iteration count."""
    q1 = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-MULTI",
        question="Q1", options=["a", "b"], correct_index=0, explanation="because",
    )
    q2 = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-MULTI",
        question="Q2", options=["a", "b"], correct_index=0, explanation="because",
    )
    db.add_all([q1, q2])
    await db.commit()

    await _make_weak_technique(db, test_user["user"], approved_scenario, "T-MULTI")

    current = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
    current_id = current.json()["id"]
    assert current_id in (q1.id, q2.id)

    for _ in range(20):
        await client.post(
            f"/api/v1/learning/knowledge-check/{current_id}/attempt",
            headers=_auth_headers(test_user["token"]),
            json={"chosen_index": 1},
        )
        nxt = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
        next_id = nxt.json()["id"]
        assert next_id != current_id
        assert next_id in (q1.id, q2.id), "should still prefer T-MULTI's own remaining question over a different technique"
        current_id = next_id


async def test_next_allows_a_repeat_rather_than_404ing_when_only_one_question_exists_at_all(client, db, test_user, approved_scenario):
    """Edge case: if the entire bank has exactly one question, excluding the
    last-answered id would leave zero candidates. Must fall back to allowing
    the repeat, not 404 a user who legitimately has nothing else to drill."""
    only = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-ONLY",
        question="Only question", options=["a", "b"], correct_index=0, explanation="because",
    )
    db.add(only)
    await db.commit()

    first = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
    assert first.status_code == 200
    assert first.json()["id"] == only.id

    await client.post(
        f"/api/v1/learning/knowledge-check/{only.id}/attempt",
        headers=_auth_headers(test_user["token"]),
        json={"chosen_index": 1},
    )

    second = await client.get("/api/v1/learning/knowledge-check/next", headers=_auth_headers(test_user["token"]))
    assert second.status_code == 200
    assert second.json()["id"] == only.id


async def test_attempt_records_a_row_and_returns_the_correct_answer(client, db, test_user, approved_scenario):
    check = KnowledgeCheck(
        scenario_id=approved_scenario.id, technique_id="T-BASIC",
        question="Basic question", options=["wrong", "right"], correct_index=1, explanation="because right is right",
    )
    db.add(check)
    await db.commit()

    resp = await client.post(
        f"/api/v1/learning/knowledge-check/{check.id}/attempt",
        headers=_auth_headers(test_user["token"]),
        json={"chosen_index": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"is_correct": True, "correct_index": 1, "explanation": "because right is right"}

    result = await db.execute(
        select(UserKnowledgeCheckAttempt).where(UserKnowledgeCheckAttempt.knowledge_check_id == check.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].is_correct is True
