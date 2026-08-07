"""
HTTP-level tests for the Phase 2.5 CMMC Evidence Layer's onboarding and
invitation flow (build-order item 2): backend/app/api/routes/cmmc.py and
POST /auth/register's combined register+redeem path.

Split out from test_cmmc_isolation.py (item 1's pure data-access tests)
since these exercise the full route stack via the `client` fixture, not
just app.services.cmmc_access directly.

The non-negotiable ones, per Femi's explicit review comments:
- a forwarded invite link (redeemed under a different email than the one
  invited) must be rejected, in BOTH redemption paths;
- redeeming into an org you're already a member of must succeed
  idempotently, not surface item 1's partial-unique-index IntegrityError
  as a 500 — the user did nothing wrong;
- email comparison must be normalised (strip + lowercase), not a bare
  case-insensitive compare, since that normalisation IS the security
  boundary.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.membership import Membership
from app.models.user import User
from app.services.cmmc_invites import get_cmmc_invite, store_cmmc_invite

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def _user(email: str, *, role: str = "analyst") -> User:
    return User(
        email=email,
        hashed_password=hash_password("StrongPass1!"),
        full_name=email,
        role=role,
        organization_id=None,
    )


async def _make_consultant_admin(db) -> tuple[User, str, ConsultingOrg]:
    org = ConsultingOrg(name=f"RPO {uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    user = _user(_unique_email("consultant"))
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, consulting_org_id=org.id, role="consultant_admin"))
    await db.flush()
    token = create_access_token({"sub": user.id})
    return user, token, org


# ── staff-gated ConsultingOrg creation ──────────────────────────────────────

async def test_non_admin_cannot_create_consulting_org(client, db):
    user = _user(_unique_email("plain"))
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})

    resp = await client.post(
        "/api/v1/admin/cmmc/consulting-orgs",
        json={"name": "New RPO", "admin_email": _unique_email("founding-admin")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


async def test_admin_creates_consulting_org_and_issues_founding_invite(client, db):
    """The gated path is the ONLY way a new ConsultingOrg comes into
    existence, and it must also issue the founding consultant_admin's
    invite through the same token mechanism as every other invite — not a
    separate bootstrap. The route never returns the raw token (only the
    invited person's email gets it), so this test finds it by scanning
    Redis, the same way a human would only ever have it via the email."""
    from app.core.redis import get_redis

    admin = _user(_unique_email("staff"), role="admin")
    db.add(admin)
    await db.flush()
    token = create_access_token({"sub": admin.id})
    founding_email = _unique_email("founding-admin")

    resp = await client.post(
        "/api/v1/admin/cmmc/consulting-orgs",
        json={"name": "New RPO", "admin_email": founding_email},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    assert resp.json()["admin_email"] == founding_email

    org = await db.get(ConsultingOrg, org_id)
    assert org is not None

    r = await get_redis()
    keys = await r.keys("cmmc_invite:*")
    assert len(keys) == 1
    invite_token = keys[0].split(":", 1)[1]
    invite = await get_cmmc_invite(invite_token)
    assert invite["email"] == founding_email
    assert invite["role"] == "consultant_admin"
    assert invite["consulting_org_id"] == org_id


# ── consultant-to-consultant invites (no staff involvement) ────────────────

async def test_consultant_admin_can_invite_peer_into_own_org(client, db):
    _, token, org = await _make_consultant_admin(db)
    resp = await client.post(
        f"/api/v1/cmmc/consulting-orgs/{org.id}/invitations",
        json={"email": _unique_email("peer")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


async def test_consultant_admin_cannot_invite_into_other_consulting_org(client, db):
    _, token_a, _ = await _make_consultant_admin(db)
    _, _, org_b = await _make_consultant_admin(db)

    resp = await client.post(
        f"/api/v1/cmmc/consulting-orgs/{org_b.id}/invitations",
        json={"email": _unique_email("intruder-invite")},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 404


# ── client-org creation + client_participant invites ────────────────────────

async def test_consultant_admin_creates_client_org_and_invites_participant(client, db):
    _, token, org = await _make_consultant_admin(db)

    create_resp = await client.post(
        f"/api/v1/cmmc/consulting-orgs/{org.id}/client-orgs",
        json={"name": "Acme Contracting", "poc_name": "Jane Doe", "poc_email": "jane@acme.example"},
        headers=auth_headers(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    client_org_id = create_resp.json()["id"]

    invite_resp = await client.post(
        f"/api/v1/cmmc/client-orgs/{client_org_id}/invitations",
        json={"email": _unique_email("participant")},
        headers=auth_headers(token),
    )
    assert invite_resp.status_code == 200, invite_resp.text


async def test_client_org_invitation_scoped_to_owning_consulting_org(client, db):
    _, token_a, org_a = await _make_consultant_admin(db)
    _, token_b, org_b = await _make_consultant_admin(db)

    create_resp = await client.post(
        f"/api/v1/cmmc/consulting-orgs/{org_a.id}/client-orgs",
        json={"name": "A's Client"},
        headers=auth_headers(token_a),
    )
    client_org_id = create_resp.json()["id"]

    # org_b's admin knows org_a's client_org id but must not be able to invite into it.
    resp = await client.post(
        f"/api/v1/cmmc/client-orgs/{client_org_id}/invitations",
        json={"email": _unique_email("cross-tenant")},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404


# ── invitation preview + redemption ─────────────────────────────────────────

async def _issue_raw_invite(*, email: str, role: str, consulting_org_id=None, client_org_id=None, invited_by_user_id="staff") -> str:
    token = str(uuid.uuid4())
    await store_cmmc_invite(
        token, email=email, role=role,
        consulting_org_id=consulting_org_id, client_org_id=client_org_id,
        invited_by_user_id=invited_by_user_id,
    )
    return token


async def test_invite_preview_returns_org_and_role(client, db):
    _, _, org = await _make_consultant_admin(db)
    token = await _issue_raw_invite(email="peer@example.com", role="consultant_admin", consulting_org_id=org.id)

    resp = await client.get(f"/api/v1/cmmc/invitations/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_name"] == org.name
    assert body["role"] == "consultant_admin"


async def test_invite_preview_unknown_token_404s(client):
    resp = await client.get(f"/api/v1/cmmc/invitations/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_redeem_rejects_mismatched_email(client, db):
    """THE test proving the forwarded-link hole is closed: an invite issued
    to one email cannot be redeemed by a different, already-registered
    user — via the standalone /redeem endpoint."""
    _, _, org = await _make_consultant_admin(db)
    invited_email = _unique_email("invited")
    token = await _issue_raw_invite(email=invited_email, role="consultant_admin", consulting_org_id=org.id)

    other_user = _user(_unique_email("not-invited"))
    db.add(other_user)
    await db.flush()
    other_token = create_access_token({"sub": other_user.id})

    resp = await client.post(f"/api/v1/cmmc/invitations/{token}/redeem", headers=auth_headers(other_token))
    assert resp.status_code == 400

    result = await db.execute(select(Membership).where(Membership.user_id == other_user.id))
    assert result.scalar_one_or_none() is None


async def test_register_with_invite_token_rejects_mismatched_email(client, db):
    """Same protection, via the combined register+redeem path."""
    _, _, org = await _make_consultant_admin(db)
    invited_email = _unique_email("invited-reg")
    token = await _issue_raw_invite(email=invited_email, role="consultant_admin", consulting_org_id=org.id)

    resp = await client.post("/api/v1/auth/register", json={
        "email": _unique_email("different"),
        "password": "StrongPass1!",
        "full_name": "Wrong Person",
        "invite_token": token,
    })
    assert resp.status_code == 400


async def test_email_match_normalises_whitespace_and_case():
    """Directly exercises the normalisation Femi called out: comparison
    must strip + lowercase, not just .lower() — a copy-pasted email with
    incidental whitespace or case differences must still match."""
    from app.services.cmmc_invites import emails_match
    assert emails_match("  Person@Example.com ", "person@example.com") is True
    assert emails_match("person@example.com", "someoneelse@example.com") is False


async def test_invite_token_is_single_use(client, db):
    _, _, org = await _make_consultant_admin(db)
    invited_email = _unique_email("single-use")
    token = await _issue_raw_invite(email=invited_email, role="consultant_admin", consulting_org_id=org.id)

    user = _user(invited_email)
    db.add(user)
    await db.flush()
    user_token = create_access_token({"sub": user.id})

    first = await client.post(f"/api/v1/cmmc/invitations/{token}/redeem", headers=auth_headers(user_token))
    assert first.status_code == 200

    second = await client.post(f"/api/v1/cmmc/invitations/{token}/redeem", headers=auth_headers(user_token))
    assert second.status_code == 404


async def test_expired_invite_token_rejected(client, db):
    """Equivalent to real TTL expiry from the app's perspective — a
    deleted/absent Redis key is indistinguishable from a timed-out one to
    get_cmmc_invite, and this repo's existing password-reset tests
    (test_auth.py) don't simulate real TTL countdowns either, for the same
    reason: fakeredis's clock isn't worth manipulating for this."""
    from app.core.redis import get_redis

    _, _, org = await _make_consultant_admin(db)
    invited_email = _unique_email("expired")
    token = await _issue_raw_invite(email=invited_email, role="consultant_admin", consulting_org_id=org.id)

    r = await get_redis()
    await r.delete(f"cmmc_invite:{token}")

    user = _user(invited_email)
    db.add(user)
    await db.flush()
    user_token = create_access_token({"sub": user.id})

    resp = await client.post(f"/api/v1/cmmc/invitations/{token}/redeem", headers=auth_headers(user_token))
    assert resp.status_code == 404


async def test_redeem_when_already_a_member_is_idempotent(client, db):
    """Approved explicitly over surfacing item 1's partial-unique-index
    IntegrityError as a 500 — redeeming a second invite into an org you're
    already a member of means the user did nothing wrong (stale bookmarked
    link, duplicate invite) and must succeed, not error."""
    _, _, org = await _make_consultant_admin(db)
    email = _unique_email("already-member")
    user = _user(email)
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, consulting_org_id=org.id, role="consultant_admin"))
    await db.flush()
    user_token = create_access_token({"sub": user.id})

    token = await _issue_raw_invite(email=email, role="consultant_admin", consulting_org_id=org.id)
    resp = await client.post(f"/api/v1/cmmc/invitations/{token}/redeem", headers=auth_headers(user_token))
    assert resp.status_code == 200, resp.text

    result = await db.execute(select(Membership).where(
        Membership.user_id == user.id, Membership.consulting_org_id == org.id,
    ))
    memberships = result.scalars().all()
    assert len(memberships) == 1


async def test_register_with_invite_token_creates_membership_atomically(client, db):
    _, _, org = await _make_consultant_admin(db)
    invited_email = _unique_email("new-user")
    token = await _issue_raw_invite(email=invited_email, role="consultant_admin", consulting_org_id=org.id)

    resp = await client.post("/api/v1/auth/register", json={
        "email": invited_email,
        "password": "StrongPass1!",
        "full_name": "New Consultant",
        "invite_token": token,
    })
    assert resp.status_code == 201, resp.text
    new_user_id = resp.json()["user"]["id"]

    result = await db.execute(select(Membership).where(Membership.user_id == new_user_id))
    membership = result.scalar_one_or_none()
    assert membership is not None
    assert membership.consulting_org_id == org.id
    assert membership.role == "consultant_admin"

    assert await get_cmmc_invite(token) is None


# ── scoping helpers used by the routes ──────────────────────────────────────

async def test_get_my_consulting_org_and_list_client_orgs(client, db):
    _, token, org = await _make_consultant_admin(db)
    resp = await client.get("/api/v1/cmmc/me/consulting-org", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == org.id

    resp2 = await client.get("/api/v1/cmmc/client-orgs", headers=auth_headers(token))
    assert resp2.status_code == 200
    assert resp2.json() == []
