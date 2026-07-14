import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class XPTransaction(Base):
    """ORM mirror of the `xp_transactions` table created by migration 0011
    (Add XP, career tier, achievements and xp_transactions). No route or
    service reads/writes through this model today — app.services.xp_service
    .award_xp inserts via raw SQL against the real table — this class exists
    solely so `Base.metadata.create_all()` (used by the pytest suite's
    SQLite fixtures, see tests/conftest.py) creates the table too. Without
    it, any test that exercises an XP award with amount > 0 fails against
    the SQLite test DB with 'no such table: xp_transactions', since that
    table otherwise only ever exists via the Alembic migration, which the
    test suite doesn't run. Keep this schema in sync with migration 0011 if
    that table is ever altered."""

    __tablename__ = "xp_transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
