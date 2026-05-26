import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class BreachDocument(Base):
    __tablename__ = "breach_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(SAEnum("processing", "completed", "failed", name="document_status"), default="processing")
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)
    uploaded_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    extracted_scenario_id: Mapped[str] = mapped_column(String, ForeignKey("scenarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    uploaded_by: Mapped["User"] = relationship("User")
    extracted_scenario: Mapped["Scenario"] = relationship("Scenario")
