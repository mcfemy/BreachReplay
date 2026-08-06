"""Phase 2.5 CMMC Evidence Layer — pack issuance and verification
(build-order item 7).

Issuance is a discrete, one-time, idempotent event — not a re-render on
every download the way item 6's plain /pack was. The bytes issued are
hashed, signed, written to ISSUED_PACKS_DIR once, and served unchanged
from then on: re-rendering on every download would mean a future
Chromium/Playwright upgrade could silently change what "the issued pack"
serves, breaking the hash it was signed under.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cmmc_signing import sign, verify as verify_signature
from app.models.cmmc_org import ClientOrg, ConsultingOrg
from app.models.evidence_session import EvidenceSession
from app.models.issued_evidence_pack import IssuedEvidencePack
from app.models.scenario import Scenario
from app.models.user import User
from app.services.cmmc_pdf import build_pack_payload, render_certifiable_pdf


async def get_issued_pack(db: AsyncSession, evidence_session_id: str) -> Optional[IssuedEvidencePack]:
    result = await db.execute(
        select(IssuedEvidencePack).where(IssuedEvidencePack.evidence_session_id == evidence_session_id)
    )
    return result.scalar_one_or_none()


def _pdf_path(document_id: str) -> str:
    os.makedirs(settings.ISSUED_PACKS_DIR, exist_ok=True)
    return os.path.join(settings.ISSUED_PACKS_DIR, f"{document_id}.pdf")


async def issue_pack(
    db: AsyncSession, session: EvidenceSession, *, issued_by: User, verify_url_base: str,
) -> IssuedEvidencePack:
    """Idempotent — returns the existing record if this session already
    has one, never re-signs or overwrites. Callers (the /issue route) own
    the export-readiness gate (dual signoff); this function doesn't
    re-check it, since it's only ever meant to run after that's already
    confirmed."""
    existing = await get_issued_pack(db, session.id)
    if existing is not None:
        return existing

    client_org = await db.get(ClientOrg, session.client_org_id)
    consulting_org = await db.get(ConsultingOrg, client_org.consulting_org_id)
    scenario = await db.get(Scenario, session.scenario_id)

    document_id = str(uuid.uuid4())
    verify_url = f"{verify_url_base}/{document_id}"

    payload = await build_pack_payload(db, session, consulting_org, client_org, scenario)
    pdf_bytes = await render_certifiable_pdf(payload, document_id=document_id, verify_url=verify_url)

    sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()
    signature_b64, key_id = sign(sha256_hash.encode())

    pdf_path = _pdf_path(document_id)
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    record = IssuedEvidencePack(
        id=document_id,
        evidence_session_id=session.id,
        sha256_hash=sha256_hash,
        signature=signature_b64,
        key_id=key_id,
        issued_by_user_id=issued_by.id,
        pdf_path=pdf_path,
    )
    db.add(record)
    await db.flush()
    return record


async def verify_pack(db: AsyncSession, document_id: str, claimed_hash: str) -> Optional[dict]:
    """None if document_id is unknown, the claimed hash doesn't match
    what was issued, or the stored signature doesn't check out — callers
    must not distinguish these cases in what they show an (anonymous,
    unauthenticated) caller, mirroring this whole layer's existing
    404-not-403 / no-existence-leakage discipline. A single altered byte
    in the caller's PDF produces a different SHA-256 and is caught here
    by the plain hash comparison; the signature re-check is an additional
    guard that the stored hash/signature/key_id are genuinely coherent,
    not a substitute for it."""
    record = await db.get(IssuedEvidencePack, document_id)
    if record is None:
        return None
    if record.sha256_hash != claimed_hash:
        return None
    if not verify_signature(record.sha256_hash.encode(), record.signature, record.key_id):
        return None

    consulting_org_name = None
    session = await db.get(EvidenceSession, record.evidence_session_id)
    if session is not None:
        client_org = await db.get(ClientOrg, session.client_org_id)
        if client_org is not None:
            consulting_org = await db.get(ConsultingOrg, client_org.consulting_org_id)
            consulting_org_name = consulting_org.name if consulting_org is not None else None

    return {
        "valid": True,
        "issued_at": record.issued_at,
        "key_id": record.key_id,
        "consulting_org_name": consulting_org_name,
    }
