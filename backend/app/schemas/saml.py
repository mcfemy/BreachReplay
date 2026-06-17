from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime


class SAMLConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=3, max_length=255, description="Email domain, e.g. acme.com")
    idp_entity_id: str = Field(min_length=1, max_length=500)
    idp_sso_url: str = Field(min_length=1, max_length=500)
    # PEM cert — with or without -----BEGIN CERTIFICATE----- headers (stripped on save)
    idp_x509_cert: str = Field(min_length=10)
    is_enabled: bool = True


class SAMLConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    domain: str
    idp_entity_id: str
    idp_sso_url: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
