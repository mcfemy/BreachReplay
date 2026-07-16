import uuid
from datetime import datetime, timedelta

import pytest

from app.models.scenario import Scenario

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_scenario(db, **overrides) -> Scenario:
    defaults = dict(
        title=f"Scenario {uuid.uuid4().hex[:8]}",
        source_type="manual",
        source_reference="TEST-REF",
        difficulty="practitioner",
        status="approved",
        is_private=False,
    )
    defaults.update(overrides)
    scenario = Scenario(**defaults)
    db.add(scenario)
    return scenario


async def test_recent_scenarios_requires_auth(client, approved_scenario):
    response = await client.get("/api/v1/scenarios/recent")
    assert response.status_code == 403


async def test_recent_scenarios_excludes_non_approved_and_private(client, db, test_user):
    approved = _make_scenario(db, title="Approved Public")
    draft = _make_scenario(db, title="Still Draft", status="draft")
    rejected = _make_scenario(db, title="Was Rejected", status="rejected")
    private = _make_scenario(db, title="Private Org Only", is_private=True)
    await db.flush()
    await db.commit()

    response = await client.get("/api/v1/scenarios/recent", headers=auth_headers(test_user["token"]))
    assert response.status_code == 200
    data = response.json()
    ids = {s["id"] for s in data}

    assert approved.id in ids
    assert draft.id not in ids
    assert rejected.id not in ids
    assert private.id not in ids

    # Lightweight shape only
    item = next(s for s in data if s["id"] == approved.id)
    assert set(item.keys()) == {
        "id", "title", "source_type", "source_reference", "industry_vertical", "created_at",
    }


async def test_recent_scenarios_ordered_newest_first(client, db, test_user):
    now = datetime.utcnow()
    older = _make_scenario(db, title="Older Incident", created_at=now - timedelta(days=2))
    newer = _make_scenario(db, title="Newer Incident", created_at=now - timedelta(minutes=5))
    await db.flush()
    await db.commit()

    # limit=25 (the endpoint's max, Query(10, ge=1, le=25)): several other
    # test files create real, non-rolled-back "approved" scenarios via
    # app.db.session.AsyncSessionLocal directly (see
    # test_action_run_ws_handler.py's module docstring for why), which
    # persist for the rest of the pytest session — a pre-existing
    # test-infra property, not something this test controls. At the
    # default limit=10, enough of those can push `older` (2 days old) out
    # of the window and this test flakes with a bare StopIteration
    # depending on what ran earlier in the session. Asking for the max
    # window sidesteps it without pretending this suite has real
    # per-test DB isolation for that class of test.
    response = await client.get(
        "/api/v1/scenarios/recent?limit=25", headers=auth_headers(test_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    older_idx = next(i for i, s in enumerate(data) if s["id"] == older.id)
    newer_idx = next(i for i, s in enumerate(data) if s["id"] == newer.id)
    assert newer_idx < older_idx


async def test_recent_scenarios_respects_limit(client, db, test_user):
    for i in range(15):
        _make_scenario(db, title=f"Bulk Incident {i}")
    await db.flush()
    await db.commit()

    response = await client.get("/api/v1/scenarios/recent", headers=auth_headers(test_user["token"]))
    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 10

    response_limited = await client.get(
        "/api/v1/scenarios/recent?limit=3", headers=auth_headers(test_user["token"])
    )
    assert response_limited.status_code == 200
    assert len(response_limited.json()) == 3
