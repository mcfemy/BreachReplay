from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from typing import Literal


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(max_length=36)
    mode: Literal["solo", "multiplayer"] = "solo"
    speed_multiplier: Optional[float] = Field(default=1.0, ge=0.5, le=5.0)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_id: str
    organization_id: Optional[str]
    host_user_id: str
    status: str
    mode: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    team_score: Optional[float]
    decisions_made: int
    decisions_correct: int
    created_at: datetime


class DecisionSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_gate_id: str = Field(min_length=1, max_length=50)
    chosen_option_index: int = Field(ge=0, le=9)
    response_time_seconds: Optional[float] = Field(default=None, ge=0, le=3600)


class DecisionResult(BaseModel):
    decision_gate_id: str
    is_correct: bool
    rationale: str
    consequence_applied: str
    nist_control_ref: str
    mitre_technique: str
    correct_index: int
