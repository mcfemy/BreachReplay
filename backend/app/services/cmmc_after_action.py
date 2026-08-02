"""Phase 2.5 CMMC Evidence Layer — after-action workflow (build-order
item 5): lessons learned, remediation items, IRP-incorporation attestation
per lesson, and dual sign-off.

No new migration — lessons_learned/remediation_items/client_signoff/
consultant_signoff have existed as empty-default JSONB columns on
EvidenceSession since item 1's stub. This module is what actually writes
to them.

Two lock semantics, deliberately different:
- AAR content (lessons) locks the moment EITHER signature exists —
  require_aar_content_unlocked. Both attestations are ABOUT the lesson
  content, so it must freeze at the FIRST signature, not just the second;
  otherwise a signed "this is accurate" could be edited out from under
  the signer.
- Remediation items are NEVER locked by sign-off. The spec's own framing
  ("track remediation items to closure") is explicitly an ongoing process
  that continues well after the exercise and after sign-off — closing an
  item weeks later as work completes is the entire point of a POA&M.
  Locking it the same way as lessons would defeat that.

Sign-off is reject-on-repeat (raises on an already-set field), never a
silent overwrite — a second "sign" call would carry a new timestamp and
would otherwise silently mutate WHEN an attestation was made, which is
exactly the kind of mutable-looking compliance record this layer exists
to avoid. Deliberately NOT idempotent, unlike item 2/3's redeem/designate
conventions, because re-signing isn't a no-op the way re-submitting an
already-applied membership or designation is.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.evidence_session import EvidenceSession
from app.models.user import User


class AfterActionError(ValueError):
    """Plain, HTTP-agnostic — routes translate this to a 400. Keeps this
    module testable without FastAPI in the loop, matching
    cmmc_evidence.py's validate_run_for_designation (returns/raises data,
    doesn't raise HTTPException itself)."""


async def validate_lesson_anchor(db: AsyncSession, session: EvidenceSession, anchor: dict) -> dict:
    """Validates {run_id, sequence_number} against the session's actual
    designated runs and that run's real action_log — raises
    AfterActionError if either doesn't check out. On success returns the
    anchor DENORMALIZED with verb/target/elapsed_seconds/participant
    identity, self-contained for rendering later without a re-join — the
    same denormalization item 3's aggregate timeline already does.

    This validation is the whole point of building the anchor now rather
    than deferring it: a fabricated or stale {run_id, sequence_number}
    would be worse than no anchor at all, since it would look specific
    without actually being checked against what happened."""
    run_id = anchor["run_id"]
    sequence_number = anchor["sequence_number"]

    run = await db.get(ActionRun, run_id)
    if run is None or run.evidence_session_id != session.id:
        raise AfterActionError("anchor run is not part of this evidence session")

    entry = next((e for e in run.action_log if e["sequence_number"] == sequence_number), None)
    if entry is None:
        raise AfterActionError("anchor sequence_number does not exist in that run's action log")

    participant_name = "Unknown participant"
    if run.user_id:
        user = await db.get(User, run.user_id)
        if user is not None:
            participant_name = user.full_name or user.email

    return {
        "run_id": run_id,
        "sequence_number": sequence_number,
        "verb": entry["verb"],
        "target": entry.get("target"),
        "elapsed_seconds": entry["elapsed_seconds"],
        "participant_user_id": run.user_id,
        "participant_name": participant_name,
    }


def require_aar_content_unlocked(session: EvidenceSession) -> None:
    """Lessons freeze the moment EITHER signature exists — see module
    docstring. Callers (lesson add/update/delete routes) raise a 400 when
    this raises."""
    if session.client_signoff is not None or session.consultant_signoff is not None:
        raise AfterActionError("Evidence session content is locked — a sign-off has already been recorded")


async def add_lesson(
    db: AsyncSession, session: EvidenceSession, *,
    text: str, anchor: Optional[dict], irp_incorporated: Optional[str], irp_note: Optional[str],
    created_by: User,
) -> dict:
    require_aar_content_unlocked(session)
    resolved_anchor = await validate_lesson_anchor(db, session, anchor) if anchor else None

    lesson = {
        "id": str(uuid.uuid4()),
        "text": text,
        "anchor": resolved_anchor,
        "irp_incorporated": irp_incorporated,
        "irp_note": irp_note,
        "created_by_user_id": created_by.id,
        "created_by_name": created_by.full_name or created_by.email,
        "created_at": datetime.utcnow().isoformat(),
    }
    session.lessons_learned = [*session.lessons_learned, lesson]
    return lesson


async def update_lesson(
    db: AsyncSession, session: EvidenceSession, lesson_id: str, changes: dict,
) -> Optional[dict]:
    require_aar_content_unlocked(session)
    if "anchor" in changes and changes["anchor"] is not None:
        changes = {**changes, "anchor": await validate_lesson_anchor(db, session, changes["anchor"])}

    updated: Optional[dict] = None
    new_lessons = []
    for lesson in session.lessons_learned:
        if lesson["id"] == lesson_id:
            lesson = {**lesson, **changes}
            updated = lesson
        new_lessons.append(lesson)
    if updated is not None:
        session.lessons_learned = new_lessons
    return updated


def remove_lesson(session: EvidenceSession, lesson_id: str) -> bool:
    require_aar_content_unlocked(session)
    original_length = len(session.lessons_learned)
    new_lessons = [entry for entry in session.lessons_learned if entry["id"] != lesson_id]
    if len(new_lessons) == original_length:
        return False
    session.lessons_learned = new_lessons
    return True


def add_remediation_item(session: EvidenceSession, fields: dict) -> dict:
    item = {
        "id": str(uuid.uuid4()),
        "status": "open",
        "closure_note": None,
        "created_at": datetime.utcnow().isoformat(),
        **fields,
    }
    session.remediation_items = [*session.remediation_items, item]
    return item


def update_remediation_item(session: EvidenceSession, item_id: str, changes: dict) -> Optional[dict]:
    updated: Optional[dict] = None
    new_items = []
    for item in session.remediation_items:
        if item["id"] == item_id:
            item = {**item, **changes}
            updated = item
        new_items.append(item)
    if updated is not None:
        session.remediation_items = new_items
    return updated


def remove_remediation_item(session: EvidenceSession, item_id: str) -> bool:
    original_length = len(session.remediation_items)
    new_items = [item for item in session.remediation_items if item["id"] != item_id]
    if len(new_items) == original_length:
        return False
    session.remediation_items = new_items
    return True


def record_signoff(session: EvidenceSession, field: str, signer: User) -> dict:
    """field is "client_signoff" or "consultant_signoff". Raises
    AfterActionError if that field is already set — see module docstring
    for why this is reject-on-repeat, not idempotent."""
    if getattr(session, field) is not None:
        raise AfterActionError(f"{field} has already been recorded")

    signoff = {
        "signed_by_user_id": signer.id,
        "signed_by_name": signer.full_name or signer.email,
        "signed_at": datetime.utcnow().isoformat(),
    }
    setattr(session, field, signoff)
    return signoff


def evidence_session_export_blockers(session: EvidenceSession) -> list[str]:
    """Empty list = ready to export. THE structural gate Femi required:
    build-order item 6 (PDF generation) MUST call this and reject if it
    returns anything, before generating a pack — this is the single
    required call site, not a convention documented elsewhere and hoped
    to be followed."""
    blockers = []
    if session.client_signoff is None:
        blockers.append("client_signoff")
    if session.consultant_signoff is None:
        blockers.append("consultant_signoff")
    return blockers
