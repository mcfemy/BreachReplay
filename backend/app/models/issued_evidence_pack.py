import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class IssuedEvidencePack(Base):
    """Build-order item 7 — the permanent record of a signed evidence
    pack. `id` doubles as the document ID printed in the pack's own
    footer and used in the public verification URL.

    `evidence_session_id` is unique: at most one issued pack per session,
    matching the /issue route's idempotent design (re-issuing returns the
    existing row rather than creating a second one). RESTRICT — same
    reasoning as every other evidence-integrity FK in this layer: a
    signed, issued artifact must never disappear as a side effect of
    deleting the session it evidences.

    `pdf_path` points at ISSUED_PACKS_DIR/{id}.pdf (app/services/
    cmmc_issuance.py) — the actual bytes that were hashed and signed,
    stored once at issuance and served unchanged on every subsequent
    download, never re-rendered. Re-rendering on every download would
    mean a future Chromium/Playwright upgrade could silently change what
    "the issued pack" serves, breaking the hash it was signed under."""

    __tablename__ = "issued_evidence_packs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    evidence_session_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_sessions.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True,
    )
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String, nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    issued_by_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    pdf_path: Mapped[str] = mapped_column(String(500), nullable=False)
