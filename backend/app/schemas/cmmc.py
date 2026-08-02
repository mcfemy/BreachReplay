from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ConsultingOrgCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr


class ConsultingOrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime


class ClientOrgCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    poc_name: Optional[str] = Field(default=None, max_length=255)
    poc_email: Optional[EmailStr] = None
    irp_reference: Optional[str] = Field(default=None, max_length=500)


class ClientOrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    consulting_org_id: str
    name: str
    poc_name: Optional[str]
    poc_email: Optional[str]
    irp_reference: Optional[str]
    created_at: datetime


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    # No `role` field, deliberately: role is implied entirely by which
    # endpoint is called (consulting-org invitations are always
    # consultant_admin, client-org invitations are always
    # client_participant). Accepting role as client input here would let a
    # caller request role="consultant_admin" on the client-org invite
    # endpoint — a privilege-escalation vector closed by not exposing the
    # field at all.


class InvitePreviewOut(BaseModel):
    org_name: str
    role: str
