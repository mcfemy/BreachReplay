from datetime import datetime
from typing import Literal, Optional

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


# ── Build-order item 3: EvidenceSession designation ─────────────────────────

class EvidenceSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    scenario_id: str
    exercise_date: datetime


class EvidenceSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    scenario_id: Optional[str] = None
    exercise_date: Optional[datetime] = None


class EvidenceSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    client_org_id: str
    title: str
    scenario_id: str
    exercise_date: datetime
    created_at: datetime


class RunSummaryOut(BaseModel):
    id: str
    user_id: Optional[str]
    participant_name: str
    scenario_id: str
    outcome: str
    total_score: int
    duration_seconds: int
    evidence_session_id: Optional[str]
    created_at: datetime


class LessonAnchorOut(BaseModel):
    run_id: str
    sequence_number: int
    verb: str
    target: Optional[str]
    elapsed_seconds: int
    participant_user_id: Optional[str]
    participant_name: str


class LessonOut(BaseModel):
    id: str
    text: str
    anchor: Optional[LessonAnchorOut]
    irp_incorporated: Optional[Literal["yes", "no", "n_a"]]
    irp_note: Optional[str]
    created_by_user_id: str
    created_by_name: str
    created_at: datetime


class RemediationItemOut(BaseModel):
    id: str
    description: str
    owner: str
    due_date: datetime
    status: Literal["open", "closed"]
    closure_note: Optional[str]
    created_at: datetime


class SignoffOut(BaseModel):
    signed_by_user_id: str
    signed_by_name: str
    signed_at: datetime


class EvidenceSessionDetailOut(EvidenceSessionOut):
    runs: list[RunSummaryOut]
    # Build-order item 5. Readable by both consultant_admin and
    # client_participant of this session (see get_evidence_session_scoped)
    # — the client needs to see exactly what they're attesting to.
    lessons_learned: list[LessonOut]
    remediation_items: list[RemediationItemOut]
    client_signoff: Optional[SignoffOut]
    consultant_signoff: Optional[SignoffOut]


class DesignateRunsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: list[str] = Field(min_length=1)


class ParticipantOutcomeOut(BaseModel):
    run_id: str
    user_id: Optional[str]
    participant_name: str
    outcome: str
    total_score: int
    score_pct: float
    # Per-participant only, deliberately never summed into a session
    # total — see EvidenceSessionAggregateOut's docstring.
    evidence_found: int
    evidence_total: int
    collateral: list[dict]
    collateral_penalty: int
    duration_seconds: int


class TimelineEntryOut(BaseModel):
    participant_user_id: Optional[str]
    participant_name: str
    sequence_number: int
    verb: str
    target: Optional[str]
    elapsed_seconds_in_run: int
    # An honest reconstruction (run.created_at - run.duration_seconds +
    # this entry's elapsed_seconds), not a real cross-participant wall
    # clock — see build_evidence_session_aggregate's docstring. Two
    # entries sharing this value are NOT being claimed as simultaneous.
    estimated_timestamp: datetime


class EvidenceSessionAggregateOut(BaseModel):
    """The per-participant / session-level view. Deliberately has no
    top-level "outcome" field of any kind — see
    app.services.cmmc_evidence.build_evidence_session_aggregate's
    docstring for the full reasoning: a team's exercise produces several
    independently graded outcomes, and `outcome_distribution` (a full
    histogram, never a scalar) is the only "how did it go" this schema
    reports."""
    evidence_session_id: str
    participant_count: int
    outcome_distribution: dict[str, int]
    participants: list[ParticipantOutcomeOut]
    collateral_total_penalty: int
    timeline: list[TimelineEntryOut]
    # Pooled escalate-verb entries only. Tells you an escalation happened,
    # who triggered it, and roughly when — NOT who was notified, since
    # verb_engine's escalate carries no target detail (a pre-existing gap,
    # not something this endpoint papers over).
    escalations: list[TimelineEntryOut]


class DesignationErrorOut(BaseModel):
    message: str
    errors: dict[str, str]


# ── Build-order item 4: notification matrix CRUD ────────────────────────────
# Field shape is the spec's own table (PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md
# section 5): authority/basis/channel/window required, last_validated/
# validation_note optional.

class NotificationMatrixEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: str = Field(min_length=1, max_length=255)
    basis: str = Field(min_length=1, max_length=255)
    channel: str = Field(min_length=1, max_length=255)
    window: str = Field(min_length=1, max_length=100)
    last_validated: Optional[datetime] = None
    validation_note: Optional[str] = Field(default=None, max_length=1000)


class NotificationMatrixEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: Optional[str] = Field(default=None, min_length=1, max_length=255)
    basis: Optional[str] = Field(default=None, min_length=1, max_length=255)
    channel: Optional[str] = Field(default=None, min_length=1, max_length=255)
    window: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_validated: Optional[datetime] = None
    validation_note: Optional[str] = Field(default=None, max_length=1000)


class NotificationMatrixEntryOut(BaseModel):
    id: str
    authority: str
    basis: str
    channel: str
    window: str
    last_validated: Optional[datetime]
    validation_note: Optional[str]


# ── Build-order item 5: after-action workflow ───────────────────────────────

class LessonAnchorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    sequence_number: int


class LessonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    # Optional per the spec ("each optionally anchored to a moment in the
    # run") — validated against the session's real runs/action_log at
    # write time (app.services.cmmc_after_action.validate_lesson_anchor),
    # not just stored as trusted freeform ids.
    anchor: Optional[LessonAnchorIn] = None
    irp_incorporated: Optional[Literal["yes", "no", "n_a"]] = None
    irp_note: Optional[str] = Field(default=None, max_length=1000)


class LessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    anchor: Optional[LessonAnchorIn] = None
    irp_incorporated: Optional[Literal["yes", "no", "n_a"]] = None
    irp_note: Optional[str] = Field(default=None, max_length=1000)


class RemediationItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=2000)
    owner: str = Field(min_length=1, max_length=255)
    due_date: datetime


class RemediationItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    owner: Optional[str] = Field(default=None, min_length=1, max_length=255)
    due_date: Optional[datetime] = None
    status: Optional[Literal["open", "closed"]] = None
    closure_note: Optional[str] = Field(default=None, max_length=1000)


class ExportReadinessOut(BaseModel):
    ready: bool
    missing: list[str]
