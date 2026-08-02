"""CMMC Evidence Layer invitation tokens — build-order item 2.

Mirrors app.core.security's password-reset token trio
(store_password_reset_token / validate_password_reset_token /
delete_password_reset_token) exactly: Redis-only, single-use via explicit
delete on redemption, TTL via setex. No DB-backed audit row — nothing in
the spec or the approved design asks for invites to be listed or revoked,
and the email-binding / single-use / expiry requirements are all
satisfiable by Redis alone. See docs/BACKLOG.md for the deliberate gap
this leaves (no "who invited whom, when" audit trail) and what would be
needed to close it later.

The payload is JSON (not a bare user_id like password reset) because an
invite has to carry enough to create a Membership on redemption: which
org, which role, who's allowed to redeem it, and who issued it.
"""
import json
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.models.membership import Membership
from app.models.user import User

_INVITE_KEY_PREFIX = "cmmc_invite"


def new_invite_token() -> str:
    return str(uuid.uuid4())


async def store_cmmc_invite(
    token: str,
    *,
    email: str,
    role: str,
    consulting_org_id: Optional[str],
    client_org_id: Optional[str],
    invited_by_user_id: str,
) -> None:
    r = await get_redis()
    payload = json.dumps({
        "email": email,
        "role": role,
        "consulting_org_id": consulting_org_id,
        "client_org_id": client_org_id,
        "invited_by_user_id": invited_by_user_id,
    })
    await r.setex(f"{_INVITE_KEY_PREFIX}:{token}", settings.CMMC_INVITE_EXPIRE_MINUTES * 60, payload)


async def get_cmmc_invite(token: str) -> Optional[dict]:
    r = await get_redis()
    raw = await r.get(f"{_INVITE_KEY_PREFIX}:{token}")
    return json.loads(raw) if raw else None


async def delete_cmmc_invite(token: str) -> None:
    r = await get_redis()
    await r.delete(f"{_INVITE_KEY_PREFIX}:{token}")


def emails_match(a: str, b: str) -> bool:
    """The whole security boundary for invite redemption — a forwarded link
    must not grant access. Normalise both sides (strip + lowercase) before
    comparing, not just a bare .lower(), since a copy-pasted email address
    picking up leading/trailing whitespace is exactly the kind of thing
    that must not silently defeat this check."""
    return a.strip().lower() == b.strip().lower()


async def redeem_invite_for_user(db: AsyncSession, user: User, invite: dict) -> None:
    """Create the Membership implied by `invite` for `user`, unless one
    already exists for that org — idempotent by design (approved
    explicitly over surfacing item 1's partial-unique-index IntegrityError
    as a 500): redeeming an invite into an org you're already a member of
    means the user did nothing wrong, most likely a stale bookmarked link
    or a duplicate invite. Shared by both redemption paths (the standalone
    /cmmc/invitations/{token}/redeem route for existing users, and
    POST /auth/register's combined register+redeem for new ones) so this
    logic exists exactly once. Callers are responsible for deleting the
    token afterward — this function only touches the Membership."""
    consulting_org_id = invite["consulting_org_id"]
    client_org_id = invite["client_org_id"]

    existing = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.consulting_org_id == consulting_org_id,
            Membership.client_org_id == client_org_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    db.add(Membership(
        user_id=user.id,
        consulting_org_id=consulting_org_id,
        client_org_id=client_org_id,
        role=invite["role"],
    ))
    await db.flush()
