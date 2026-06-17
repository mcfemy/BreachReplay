import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class OrganizationSAMLConfig(Base):
    __tablename__ = "organization_saml_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, unique=True
    )
    # Email domain used to route SSO (e.g. "acme.com")
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    idp_entity_id: Mapped[str] = mapped_column(String(500), nullable=False)
    idp_sso_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # PEM cert without -----BEGIN/END CERTIFICATE----- headers
    idp_x509_cert: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    organization: Mapped["Organization"] = relationship("Organization")
