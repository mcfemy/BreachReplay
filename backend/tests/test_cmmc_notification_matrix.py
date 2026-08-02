"""
HTTP-level tests for the Phase 2.5 CMMC Evidence Layer's notification
matrix CRUD (build-order item 4): backend/app/api/routes/cmmc.py's
notification-matrix routes and app/services/cmmc_notification_matrix.py.

Kept as a JSONB list on ClientOrg (item 1's original choice, reaffirmed
for this item rather than split into a table) — these tests exercise the
CRUD surface built on top of that: add/list/update/remove entries
addressed by a server-generated id, consultant_admin-only gating matching
every other CMMC route, and that a partial update only touches the
fields it was actually given.
"""
import uuid

import pytest

from app.core.security import create_access_token, hash_password
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.membership import Membership
from app.models.user import User

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


async def _make_client_org(db, consulting_org: ConsultingOrg) -> ClientOrg:
    client_org = ClientOrg(consulting_org_id=consulting_org.id, name=f"Client {uuid.uuid4().hex[:6]}")
    db.add(client_org)
    await db.flush()
    return client_org


async def _make_participant(db, client_org: ClientOrg) -> tuple[User, str]:
    user = _user(_unique_email("participant"))
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, client_org_id=client_org.id, role="client_participant"))
    await db.flush()
    token = create_access_token({"sub": user.id})
    return user, token


_ENTRY_PAYLOAD = {
    "authority": "DC3",
    "basis": "DFARS 252.204-7012",
    "channel": "DIBNet portal",
    "window": "72 hours",
}


async def test_consultant_admin_full_crud_flow(client, db):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    await db.commit()
    headers = auth_headers(token)
    base = f"/api/v1/cmmc/client-orgs/{client_org.id}/notification-matrix"

    empty = await client.get(base, headers=headers)
    assert empty.status_code == 200
    assert empty.json() == []

    create_resp = await client.post(base, json=_ENTRY_PAYLOAD, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    entry = create_resp.json()
    assert entry["authority"] == "DC3"
    assert entry["last_validated"] is None
    entry_id = entry["id"]

    list_resp = await client.get(base, headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == entry_id

    update_resp = await client.patch(f"{base}/{entry_id}", json={"channel": "phone"}, headers=headers)
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["channel"] == "phone"
    # Untouched fields must survive a partial update unchanged.
    assert updated["authority"] == "DC3"
    assert updated["basis"] == "DFARS 252.204-7012"
    assert updated["window"] == "72 hours"

    delete_resp = await client.delete(f"{base}/{entry_id}", headers=headers)
    assert delete_resp.status_code == 200

    final_list = await client.get(base, headers=headers)
    assert final_list.json() == []


async def test_last_validated_optional_and_round_trips(client, db):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    await db.commit()
    base = f"/api/v1/cmmc/client-orgs/{client_org.id}/notification-matrix"

    payload = {**_ENTRY_PAYLOAD, "last_validated": "2026-01-15T00:00:00", "validation_note": "Tested during Q1 tabletop"}
    resp = await client.post(base, json=payload, headers=auth_headers(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["last_validated"].startswith("2026-01-15")
    assert body["validation_note"] == "Tested during Q1 tabletop"


async def test_create_requires_required_fields(client, db):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    await db.commit()
    base = f"/api/v1/cmmc/client-orgs/{client_org.id}/notification-matrix"

    resp = await client.post(base, json={"authority": "DC3"}, headers=auth_headers(token))
    assert resp.status_code == 422


async def test_update_and_remove_nonexistent_entry_404s(client, db):
    _, token, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    await db.commit()
    base = f"/api/v1/cmmc/client-orgs/{client_org.id}/notification-matrix"
    fake_id = str(uuid.uuid4())

    update_resp = await client.patch(f"{base}/{fake_id}", json={"channel": "phone"}, headers=auth_headers(token))
    assert update_resp.status_code == 404

    delete_resp = await client.delete(f"{base}/{fake_id}", headers=auth_headers(token))
    assert delete_resp.status_code == 404


async def test_consultant_b_cannot_access_consultant_a_notification_matrix(client, db):
    _, token_a, org_a = await _make_consultant_admin(db)
    _, token_b, _ = await _make_consultant_admin(db)
    client_org_a = await _make_client_org(db, org_a)
    await db.commit()
    base = f"/api/v1/cmmc/client-orgs/{client_org_a.id}/notification-matrix"
    headers_b = auth_headers(token_b)

    assert (await client.get(base, headers=headers_b)).status_code == 404
    assert (await client.post(base, json=_ENTRY_PAYLOAD, headers=headers_b)).status_code == 404
    assert (await client.patch(f"{base}/{uuid.uuid4()}", json={"channel": "x"}, headers=headers_b)).status_code == 404
    assert (await client.delete(f"{base}/{uuid.uuid4()}", headers=headers_b)).status_code == 404


async def test_client_participant_cannot_access_notification_matrix(client, db):
    _, _, org = await _make_consultant_admin(db)
    client_org = await _make_client_org(db, org)
    _, participant_token = await _make_participant(db, client_org)
    await db.commit()
    base = f"/api/v1/cmmc/client-orgs/{client_org.id}/notification-matrix"
    headers = auth_headers(participant_token)

    assert (await client.get(base, headers=headers)).status_code == 404
    assert (await client.post(base, json=_ENTRY_PAYLOAD, headers=headers)).status_code == 404
    assert (await client.patch(f"{base}/{uuid.uuid4()}", json={"channel": "x"}, headers=headers)).status_code == 404
    assert (await client.delete(f"{base}/{uuid.uuid4()}", headers=headers)).status_code == 404
