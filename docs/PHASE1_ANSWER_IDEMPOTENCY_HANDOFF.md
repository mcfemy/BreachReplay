# BreachReplay Phase 1 — `/teaser/answer` idempotency fix (handoff)

**Repo:** github.com/mcfemy/breachreplay
**Branch:** `phase-1-teaser` (PR #1)
**Status:** Phase 1 is NOT signed off until this lands. Do not merge PR #1 first.

---

## Why this exists

During checkpoint review of PR #1, the previously flagged `/teaser/answer`
bug was found to still be live. It was never fixed in either Phase 1 commit
(`9fc3956` backend, `a27ca9f` frontend). The "Phase 1 complete" handoff was
raised without closing this item.

### The bug

`POST /teaser/answer` wrote a `teaser_decided` + `teaser_completed` row on
**every** call, with no guard, and `TeaserEvent.token_id` is not unique. So a
single anonymous token could:

1. **Correct its answer** — answer wrong, then call again with the right node
   and get a "correct" result.
2. **Inflate the funnel** — stack duplicate `teaser_decided`/`teaser_completed`
   rows, corrupting the `COUNT(*) GROUP BY event_type` funnel metrics.

The frontend `answeredRef` guard (in `TeaserLandingPage.tsx`) only stops an
honest user double-clicking in one session. It does nothing against direct API
calls, reloads, or a second tab. The server is authoritative for metrics and
had no dedup.

---

## The fix (verified, not just claimed)

`/teaser/answer` is now **first-answer-wins**. Before doing anything, it looks
up an existing `teaser_decided` event for the token. If one exists, it
reconstructs the response from the stored outcome and returns **without**
writing new rows and **without** reading the incoming `chosen_node_id`. Fresh
answers behave exactly as before. Response-building was pulled into a shared
`_build_answer_response(correct)` helper so the fresh path and the replay path
cannot drift.

A new test `test_answer_is_first_answer_wins_and_writes_a_single_decision`
answers wrong (`DC-01`), re-answers with the correct node (`MAIL-01`), asserts
the second response equals the first, and asserts exactly one `teaser_decided`
and one `teaser_completed` row exist.

### Verification run

```
pytest tests/test_teaser.py
11 passed, 98 warnings in 1.62s
```

All 11 teaser tests pass, including the new one. (The 98 warnings are
pre-existing `datetime.utcnow()` deprecation noise across the codebase, not
introduced by this change.)

---

## How to apply

From repo root, either apply the patch below:

```bash
git apply <<'PATCH'
<paste the patch block from the "Patch" section below>
PATCH

cd backend && pytest tests/test_teaser.py
```

…or make the two edits manually as shown in the "Full changes" section, then
run the same test command.

After it's green, re-request review before merging PR #1.

---

## Full changes

### 1. `backend/app/api/routes/teaser.py`

Add a module-level helper and rewrite the `/answer` handler. The new
`_build_answer_response` helper goes directly **above** the
`@router.post("/answer")` decorator; the handler body is replaced.

```python
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
```

`select` and `TeaserEvent` are already imported at the top of this file, so no
new imports are needed here.

### 2. `backend/tests/test_teaser.py`

Add two imports at the top:

```python
from sqlalchemy import func, select
from app.models.teaser_event import TeaserEvent
```

Add this test (placed after `test_answer_wrong_choice_bleeds_to_two_more_hosts`):

```python
async def test_answer_is_first_answer_wins_and_writes_a_single_decision(client, db):
    """A token's first /answer is final. Re-calling with a different node must
    return the original outcome (no answer correction) and must not write more
    decided/completed rows (no funnel inflation)."""
    data = await _start(client)
    token = data["teaser_token"]

    # First answer is a wrong pick.
    first = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": token,
        "chosen_node_id": "DC-01",
    })
    assert first.status_code == 200
    assert first.json()["correct"] is False

    # Second answer tries to switch to the correct node — must be ignored.
    second = await client.post("/api/v1/teaser/answer", json={
        "teaser_token": token,
        "chosen_node_id": "MAIL-01",
    })
    assert second.status_code == 200
    assert second.json() == first.json()

    # Exactly one decided and one completed row were written (the test runs in
    # an isolated, rolled-back transaction, so these are this token's only rows).
    for event_type in ("teaser_decided", "teaser_completed"):
        count = await db.scalar(
            select(func.count())
            .select_from(TeaserEvent)
            .where(TeaserEvent.event_type == event_type)
        )
        assert count == 1, f"expected exactly one {event_type} row, found {count}"
```

---

## Patch (git apply)

```diff
diff --git a/backend/app/api/routes/teaser.py b/backend/app/api/routes/teaser.py
index 86dcaf6..aee9059 100644
--- a/backend/app/api/routes/teaser.py
+++ b/backend/app/api/routes/teaser.py
@@ -91,15 +91,10 @@ async def start_teaser(request: Request, db: AsyncSession = Depends(get_db)):
     }
 
 
-@router.post("/answer")
-@limiter.limit("20/minute")
-async def answer_teaser(request: Request, payload: TeaserAnswerRequest, db: AsyncSession = Depends(get_db)):
-    token_id = _verify_teaser_token(payload.teaser_token)
-
-    if payload.chosen_node_id not in teaser_data.DECISION["node_choices"]:
-        raise HTTPException(status_code=400, detail="Invalid node choice")
-
-    correct = payload.chosen_node_id == teaser_data.TEASER_CORRECT_NODE_ID
+def _build_answer_response(correct: bool) -> dict:
+    """Deterministic answer payload for a given outcome. Shared by the fresh
+    path and the first-answer-wins replay path so a repeated /answer call
+    reconstructs the exact same body from the stored outcome."""
     if correct:
         node_states = {teaser_data.TEASER_CORRECT_NODE_ID: "contained"}
         consequence_text = teaser_data.CONSEQUENCE_CORRECT
@@ -109,6 +104,38 @@ async def answer_teaser(request: Request, payload: TeaserAnswerRequest, db: Asyn
             node_states[node_id] = "compromised"
         consequence_text = teaser_data.CONSEQUENCE_WRONG
 
+    return {
+        "correct": correct,
+        "node_states": node_states,
+        "consequence_text": consequence_text,
+        "end_card_text": teaser_data.END_CARD_TEXT,
+    }
+
+
+@router.post("/answer")
+@limiter.limit("20/minute")
+async def answer_teaser(request: Request, payload: TeaserAnswerRequest, db: AsyncSession = Depends(get_db)):
+    token_id = _verify_teaser_token(payload.teaser_token)
+
+    # First-answer-wins. If this token already recorded a decision, return that
+    # original outcome and write nothing. This blocks two abuses: (1) re-calling
+    # with a different node to "correct" a wrong pick, and (2) stacking
+    # duplicate decided/completed rows that would inflate the funnel counts.
+    # The incoming chosen_node_id is deliberately ignored on a replay, so the
+    # answer can't be revised after the fact.
+    prior_decided = await db.execute(
+        select(TeaserEvent)
+        .where(TeaserEvent.token_id == token_id, TeaserEvent.event_type == "teaser_decided")
+        .limit(1)
+    )
+    prior = prior_decided.scalar_one_or_none()
+    if prior is not None:
+        return _build_answer_response(prior.outcome == "correct")
+
+    if payload.chosen_node_id not in teaser_data.DECISION["node_choices"]:
+        raise HTTPException(status_code=400, detail="Invalid node choice")
+
+    correct = payload.chosen_node_id == teaser_data.TEASER_CORRECT_NODE_ID
     outcome = "correct" if correct else "wrong"
     now = datetime.utcnow()
     # "decided" and "completed" both fire off this single call — a teaser
@@ -120,12 +147,7 @@ async def answer_teaser(request: Request, payload: TeaserAnswerRequest, db: Asyn
                         scenario_key=teaser_data.SCENARIO_KEY, outcome=outcome, created_at=now))
     await db.commit()
 
-    return {
-        "correct": correct,
-        "node_states": node_states,
-        "consequence_text": consequence_text,
-        "end_card_text": teaser_data.END_CARD_TEXT,
-    }
+    return _build_answer_response(correct)
 
 
 @router.post("/claim")
diff --git a/backend/tests/test_teaser.py b/backend/tests/test_teaser.py
index 51ff38e..3ce2750 100644
--- a/backend/tests/test_teaser.py
+++ b/backend/tests/test_teaser.py
@@ -2,9 +2,11 @@ from datetime import datetime, timedelta
 
 import pytest
 from jose import jwt as jose_jwt
+from sqlalchemy import func, select
 
 from app.core.config import settings
 from app.core.security import limiter
+from app.models.teaser_event import TeaserEvent
 
 pytestmark = pytest.mark.asyncio
 
@@ -54,6 +56,40 @@ async def test_answer_wrong_choice_bleeds_to_two_more_hosts(client):
     assert body["node_states"] == {"MAIL-01": "compromised", "DC-01": "compromised", "FIN-03": "compromised"}
 
 
+async def test_answer_is_first_answer_wins_and_writes_a_single_decision(client, db):
+    """A token's first /answer is final. Re-calling with a different node must
+    return the original outcome (no answer correction) and must not write more
+    decided/completed rows (no funnel inflation)."""
+    data = await _start(client)
+    token = data["teaser_token"]
+
+    # First answer is a wrong pick.
+    first = await client.post("/api/v1/teaser/answer", json={
+        "teaser_token": token,
+        "chosen_node_id": "DC-01",
+    })
+    assert first.status_code == 200
+    assert first.json()["correct"] is False
+
+    # Second answer tries to switch to the correct node — must be ignored.
+    second = await client.post("/api/v1/teaser/answer", json={
+        "teaser_token": token,
+        "chosen_node_id": "MAIL-01",
+    })
+    assert second.status_code == 200
+    assert second.json() == first.json()
+
+    # Exactly one decided and one completed row were written (the test runs in
+    # an isolated, rolled-back transaction, so these are this token's only rows).
+    for event_type in ("teaser_decided", "teaser_completed"):
+        count = await db.scalar(
+            select(func.count())
+            .select_from(TeaserEvent)
+            .where(TeaserEvent.event_type == event_type)
+        )
+        assert count == 1, f"expected exactly one {event_type} row, found {count}"
+
+
 async def test_answer_rejects_a_node_not_offered_as_a_choice(client):
     data = await _start(client)
     resp = await client.post("/api/v1/teaser/answer", json={
```

---

## Known caveat (not a blocker)

The guard is a read-then-write, so two truly simultaneous requests with the
same token could both pass the check and double-write. For a single anonymous
user trying to correct an answer or pad the funnel, that race is not reachable
in practice. If airtight is wanted later, the proper hardening is a Postgres
**partial unique index** on `token_id WHERE event_type = 'teaser_decided'`.
That won't run under the SQLite test fixture, so it was deliberately kept out
of this fix to avoid splitting behavior between test and prod. Track it as a
Phase 2 hardening item.
