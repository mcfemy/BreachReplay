"""Tests for Live Arena Mode Phase I: matchmaking queue + leaderboard REST
endpoints (app/api/routes/arena.py's queue/* and leaderboard routes,
backed by app/services/arena_matchmaking_service.py).

Queue state lives on the shared, module-level `manager` singleton
(in-process, not per-test-transaction like the DB), so every test cleans
up its own queue entries in a `finally` block to avoid leaking state into
other tests in the same session — the same pattern already used for
`manager.arena_defender_bot_responses` elsewhere in this test suite.
"""
import pytest

from app.models.user import User
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _second_user(db, test_org):
    from app.core.security import create_access_token, hash_password

    user = User(
        email="second-player@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Second Player",
        role="analyst",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": user}


# ── Matchmaking queue ────────────────────────────────────────────────────────

async def test_solo_join_reports_waiting_with_an_estimate(client, test_user):
    try:
        resp = await client.post("/api/v1/arena/queue/join", headers=auth_headers(test_user["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["match_id"] is None
        assert data["estimated_wait_seconds"] > 0
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


async def test_rejoining_while_already_queued_is_idempotent(client, test_user):
    try:
        first = await client.post("/api/v1/arena/queue/join", headers=auth_headers(test_user["token"]))
        second = await client.post("/api/v1/arena/queue/join", headers=auth_headers(test_user["token"]))
        assert first.json()["status"] == "waiting"
        assert second.json()["status"] == "waiting"
        assert len(manager.arena_queue) == 1
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


async def test_two_different_users_joining_get_paired(client, db, test_org, test_user):
    other = await _second_user(db, test_org)
    await db.commit()
    try:
        first_join = await client.post("/api/v1/arena/queue/join", headers=auth_headers(test_user["token"]))
        assert first_join.json()["status"] == "waiting"

        second_join = await client.post("/api/v1/arena/queue/join", headers=auth_headers(other["token"]))
        assert second_join.json()["status"] == "matched"
        match_id = second_join.json()["match_id"]
        assert match_id is not None

        # The first user hasn't polled again yet, but IS matched — their
        # own next status call must surface the SAME match_id.
        first_status = await client.get("/api/v1/arena/queue/status", headers=auth_headers(test_user["token"]))
        assert first_status.json()["status"] == "matched"
        assert first_status.json()["match_id"] == match_id

        # Consumed: polling again reports not_queued, not a re-delivery.
        first_status_again = await client.get("/api/v1/arena/queue/status", headers=auth_headers(test_user["token"]))
        assert first_status_again.json()["status"] == "not_queued"

        # The resulting match is a real, playable PvP match with both users
        # assigned to exactly the two roles (order may be randomized).
        match_get = await client.get(f"/api/v1/arena/matches/{match_id}", headers=auth_headers(test_user["token"]))
        assert match_get.status_code == 200
        match_data = match_get.json()
        assert match_data["mode"] == "pvp"
        assert {match_data["attacker_user_id"], match_data["defender_user_id"]} == {test_user["user"].id, other["user"].id}
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)
        manager.arena_queue.pop(other["user"].id, None)


async def test_leave_queue_removes_a_waiting_entry(client, test_user):
    try:
        await client.post("/api/v1/arena/queue/join", headers=auth_headers(test_user["token"]))
        leave_resp = await client.request("DELETE", "/api/v1/arena/queue/leave", headers=auth_headers(test_user["token"]))
        assert leave_resp.status_code == 200
        assert leave_resp.json()["left"] is True

        status_resp = await client.get("/api/v1/arena/queue/status", headers=auth_headers(test_user["token"]))
        assert status_resp.json()["status"] == "not_queued"
    finally:
        manager.arena_queue.pop(test_user["user"].id, None)


async def test_leave_queue_when_not_queued_is_a_no_op(client, test_user):
    resp = await client.request("DELETE", "/api/v1/arena/queue/leave", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    assert resp.json()["left"] is False


# ── Leaderboard ──────────────────────────────────────────────────────────────

async def test_leaderboard_excludes_users_with_no_matches_played(client, test_user):
    resp = await client.get("/api/v1/arena/leaderboard", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    assert all(entry["user_id"] != test_user["user"].id for entry in resp.json())


async def test_leaderboard_lists_and_ranks_players_who_have_played(client, db, test_org, test_user, admin_user):
    test_user["user"].arena_matches_played = 3
    test_user["user"].arena_rating = 1300
    test_user["user"].arena_wins = 2
    test_user["user"].arena_losses = 1
    admin_user["user"].arena_matches_played = 5
    admin_user["user"].arena_rating = 1450
    admin_user["user"].arena_wins = 4
    admin_user["user"].arena_losses = 1
    await db.commit()

    resp = await client.get("/api/v1/arena/leaderboard", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    data = resp.json()

    entries_by_id = {e["user_id"]: e for e in data}
    assert admin_user["user"].id in entries_by_id
    assert test_user["user"].id in entries_by_id
    # Higher rating ranks first.
    assert entries_by_id[admin_user["user"].id]["rank"] < entries_by_id[test_user["user"].id]["rank"]
    assert entries_by_id[test_user["user"].id]["is_current_user"] is True
    assert entries_by_id[admin_user["user"].id]["is_current_user"] is False
    assert entries_by_id[test_user["user"].id]["arena_wins"] == 2
