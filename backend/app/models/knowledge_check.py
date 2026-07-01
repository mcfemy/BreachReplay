import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class KnowledgeCheck(Base):
    __tablename__ = "knowledge_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=True, index=True)
    technique_id: Mapped[str] = mapped_column(String(50), nullable=True, index=True)
    nist_control_ref: Mapped[str] = mapped_column(String(50), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    correct_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class UserKnowledgeCheckAttempt(Base):
    __tablename__ = "user_knowledge_check_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_check_id: Mapped[str] = mapped_column(String, ForeignKey("knowledge_checks.id", ondelete="CASCADE"), nullable=False, index=True)
    chosen_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
