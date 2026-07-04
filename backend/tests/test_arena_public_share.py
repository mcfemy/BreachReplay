"""Tests for Live Breach Events Phase 1: public shareable Arena match replay
links.

Covers three routes:
  1. POST /arena/matches/{id}/share            — auth, participant-only,
     mints/returns an idempotent share_token for a completed match.
  2. GET  /arena/public/replay/{share_token}    — no auth, redacted
     summary-only replay for a completed match's token.
  3. PATCH /users/me/public-profile             — auth, opt-in public
     display handle + arena_profile_public toggle.

Mirrors test_arena_explore.py / test_arena_phase_h.py's conventions: the
`client`/`db`/`test_user`/`admin_user` fixtures from conftest.py, real
`ArenaMatch` rows built directly against the `db` fixture, and
`auth_headers(token)` for bearer-token auth.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.arena import ArenaMatch
from app.models.user import User

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_match(
    db,
    attacker_id,
    defender_id,
    status="attacker_won",
    seed=42,
    archetype_key="small_healthcare",
    final_org_state_cache=None,
):
    match = ArenaMatch(
        id=str(uuid.uuid4()),
        seed=seed,
        archetype_key=archetype_key,
        mode="pvp",
        attacker_user_id=attacker_id,
        defender_user_id=defender_id,
        status=status,
        final_org_state_cache=final_org_state_cache if final_org_state_cache is not None else {"hosts": [], "segments": []},
    )
    db.add(match)
    await db.flush()
    await db.commit()
    await db.refresh(match)
    return match


# ── POST /arena/matches/{id}/share ──────────────────────────────────────────

async def test_share_rejects_non_participant(client, db, test_user, admin_user):
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)

    other = User(
        email="outsider-share@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Outsider",
        role="analyst",
        organization_id=test_user["org"].id,
    )
    db.add(other)
    await db.flush()
    other_token = create_access_token({"sub": other.id})
    await db.commit()

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 403


async def test_share_rejects_non_terminal_match(client, db, test_user, admin_user):
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id, status="active")

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 400


async def test_share_returns_404_for_unknown_match(client, test_user):
    resp = await client.post(
        f"/api/v1/arena/matches/{uuid.uuid4()}/share",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 404


async def test_share_mints_token_for_attacker(client, db, test_user, admin_user):
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["share_token"]
    assert data["share_url_path"] == f"/replay/{data['share_token']}"

    res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match.id))
    m = res.scalar_one()
    assert m.share_token == data["share_token"]


async def test_share_is_idempotent_no_new_token_minted(client, db, test_user, admin_user):
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)

    resp1 = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    resp2 = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["share_token"] == resp2.json()["share_token"]


async def test_share_works_for_defender_too(client, db, test_user, admin_user):
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)

    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(admin_user["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["share_token"]


# ── GET /arena/public/replay/{share_token} ──────────────────────────────────

async def test_public_replay_404_for_unknown_token(client):
    resp = await client.get("/api/v1/arena/public/replay/does-not-exist")
    assert resp.status_code == 404


async def test_public_replay_404_when_token_set_but_status_not_terminal(client, db, test_user, admin_user):
    """Defense-in-depth: even if a match somehow has a share_token set while
    its status is not terminal (should never happen via the real mint path,
    but the public route must not trust the token's mere presence), the
    route must 404 exactly like an unknown token."""
    match = await _make_match(db, test_user["user"].id, admin_user["user"].id, status="active")
    match.share_token = "defense-in-depth-token"
    db.add(match)
    await db.commit()

    resp = await client.get(f"/api/v1/arena/public/replay/{match.share_token}")
    assert resp.status_code == 404


async def test_public_replay_200_with_correct_fields(client, db, test_user, admin_user):
    state_cache = {"hosts": [{"id": "h1", "compromise_level": "admin"}], "segments": []}
    match = await _make_match(
        db, test_user["user"].id, admin_user["user"].id, final_org_state_cache=state_cache,
    )
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    token = resp.json()["share_token"]

    public_resp = await client.get(f"/api/v1/arena/public/replay/{token}")
    assert public_resp.status_code == 200
    data = public_resp.json()
    assert data["archetype_key"] == match.archetype_key
    assert data["mode"] == "pvp"
    assert data["status"] == "attacker_won"
    assert data["action_count"] == 0
    assert data["state"] == state_cache
    assert data["events"] == []
    assert "attacker_label" in data
    assert "defender_label" in data


async def test_public_replay_label_falls_back_to_placeholder_when_not_public(client, db, test_user, admin_user):
    test_user["user"].arena_profile_public = False
    test_user["user"].public_display_handle = None
    db.add(test_user["user"])
    await db.commit()

    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    token = resp.json()["share_token"]

    public_resp = await client.get(f"/api/v1/arena/public/replay/{token}")
    assert public_resp.status_code == 200
    data = public_resp.json()
    assert data["attacker_label"] == "Player A"


async def test_public_replay_label_shows_real_handle_when_opted_in(client, db, test_user, admin_user):
    test_user["user"].arena_profile_public = True
    test_user["user"].public_display_handle = "cyber_hero_1"
    db.add(test_user["user"])
    await db.commit()

    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    token = resp.json()["share_token"]

    public_resp = await client.get(f"/api/v1/arena/public/replay/{token}")
    assert public_resp.status_code == 200
    data = public_resp.json()
    assert data["attacker_label"] == "cyber_hero_1"


async def test_public_replay_contains_no_raw_user_id_or_full_name(client, db, test_user, admin_user):
    """The public replay must never leak the raw user_id or full_name of
    either participant anywhere in the response — those are opted OUT of by
    default (full_name may be a real OAuth name)."""
    test_user["user"].arena_profile_public = False
    db.add(test_user["user"])
    await db.commit()

    match = await _make_match(db, test_user["user"].id, admin_user["user"].id)
    resp = await client.post(
        f"/api/v1/arena/matches/{match.id}/share",
        headers=auth_headers(test_user["token"]),
    )
    token = resp.json()["share_token"]

    public_resp = await client.get(f"/api/v1/arena/public/replay/{token}")
    assert public_resp.status_code == 200
    body_text = public_resp.text
    assert test_user["user"].id not in body_text
    assert admin_user["user"].id not in body_text
    assert test_user["user"].full_name not in body_text
    assert admin_user["user"].full_name not in body_text


# ── PATCH /users/me/public-profile ──────────────────────────────────────────

async def test_update_public_profile_requires_auth(client):
    resp = await client.patch(
        "/api/v1/users/me/public-profile",
        json={"public_display_handle": "someone", "arena_profile_public": True},
    )
    assert resp.status_code in (401, 403)


async def test_update_public_profile_rejects_invalid_handle(client, test_user):
    resp = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "ab"},  # too short (< 3 chars)
    )
    assert resp.status_code == 422

    resp2 = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "has-a-hyphen"},  # hyphen not allowed
    )
    assert resp2.status_code == 422


async def test_update_public_profile_rejects_taken_handle(client, db, test_user, admin_user):
    admin_user["user"].public_display_handle = "taken_handle"
    db.add(admin_user["user"])
    await db.commit()

    resp = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "taken_handle"},
    )
    assert resp.status_code == 409


async def test_update_public_profile_persists_both_fields(client, db, test_user):
    resp = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "valid_handle_1", "arena_profile_public": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["public_display_handle"] == "valid_handle_1"
    assert data["arena_profile_public"] is True

    res = await db.execute(select(User).where(User.id == test_user["user"].id))
    u = res.scalar_one()
    assert u.public_display_handle == "valid_handle_1"
    assert u.arena_profile_public is True


async def test_update_public_profile_partial_update_leaves_other_field_untouched(client, db, test_user):
    # First, set both fields to a known baseline.
    first = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "baseline_handle", "arena_profile_public": True},
    )
    assert first.status_code == 200

    # Now send only arena_profile_public=False — the handle must be untouched.
    second = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"arena_profile_public": False},
    )
    assert second.status_code == 200
    data = second.json()
    assert data["public_display_handle"] == "baseline_handle"
    assert data["arena_profile_public"] is False


# ── GET /users/me/public-profile ────────────────────────────────────────────

async def test_get_public_profile_requires_auth(client):
    resp = await client.get("/api/v1/users/me/public-profile")
    assert resp.status_code in (401, 403)


async def test_get_public_profile_returns_current_values(client, db, test_user):
    patch_resp = await client.patch(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
        json={"public_display_handle": "hydrate_me", "arena_profile_public": True},
    )
    assert patch_resp.status_code == 200

    get_resp = await client.get(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(test_user["token"]),
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["public_display_handle"] == "hydrate_me"
    assert data["arena_profile_public"] is True


async def test_get_public_profile_defaults_for_new_user(client, admin_user):
    """A user who has never opted in gets the default shape back, not a 404
    or an error — the GET route has no side effects and must never mint or
    change anything."""
    resp = await client.get(
        "/api/v1/users/me/public-profile",
        headers=auth_headers(admin_user["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "public_display_handle" in data
    assert "arena_profile_public" in data
