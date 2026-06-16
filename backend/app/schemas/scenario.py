from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Any
from datetime import datetime
from typing import Literal

_MITRE_RE = __import__("re").compile(r'^T\d{4}(\.\d{3})?$')
_NIST_RE = __import__("re").compile(r'^[A-Z]{2}\.[A-Z]{2}-\d+$')

IndustryVertical = Literal[
    "healthcare", "energy", "finance", "government",
    "technology", "retail", "education", "other"
]
Difficulty = Literal["awareness", "practitioner", "expert"]
SourceType = Literal[
    "cisa", "sec_8k", "hhs", "verizon_dbir", "private", "manual"
]


class AlertObject(BaseModel):
    timestamp: str = Field(max_length=20)
    severity: Literal["critical", "high", "medium", "low"]
    source_system: str = Field(max_length=50)
    rule_id: str = Field(max_length=50)
    description: str = Field(max_length=1000)
    raw_log: Optional[str] = Field(default=None, max_length=2000)


class DecisionOption(BaseModel):
    text: str = Field(max_length=500)
    consequence_if_chosen: str = Field(max_length=1000)


class DecisionGate(BaseModel):
    id: str = Field(max_length=50)
    trigger_timestamp: str = Field(max_length=20)
    context_summary: str = Field(max_length=2000)
    options: List[DecisionOption] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0, le=5)
    consequence_if_wrong: str = Field(max_length=1000)
    rationale: str = Field(max_length=2000)
    nist_control_ref: str = Field(max_length=20)
    mitre_technique: str = Field(max_length=10)


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    source_type: SourceType
    source_url: Optional[str] = Field(default=None, max_length=2000)
    source_reference: Optional[str] = Field(default=None, max_length=500)
    incident_date: Optional[datetime] = None
    incident_duration_hours: Optional[float] = Field(default=None, ge=0, le=87600)
    industry_vertical: Optional[IndustryVertical] = None
    initial_access_vector: Optional[str] = Field(default=None, max_length=100)
    affected_asset_types: Optional[List[str]] = Field(default=None, max_length=20)
    mitre_techniques: Optional[List[str]] = Field(default=None, max_length=50)
    nist_controls: Optional[List[str]] = Field(default=None, max_length=50)
    regulatory_frameworks: Optional[List[str]] = Field(default=None, max_length=20)
    difficulty: Optional[Difficulty] = "practitioner"
    estimated_minutes: Optional[int] = Field(default=45, ge=5, le=480)
    compression_ratio: Optional[float] = Field(default=8.0, ge=1.0, le=100.0)
    alert_sequence: Optional[List[Any]] = None
    decision_tree: Optional[List[Any]] = None
    is_private: Optional[bool] = False
    owner_org_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator("mitre_techniques", mode="before")
    @classmethod
    def validate_mitre(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for t in v:
            if not _MITRE_RE.match(t):
                raise ValueError(f"Invalid MITRE technique ID: {t!r}")
        return v

    @field_validator("nist_controls", mode="before")
    @classmethod
    def validate_nist(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for c in v:
            if not _NIST_RE.match(c):
                raise ValueError(f"Invalid NIST control ID: {c!r}")
        return v

    @field_validator("affected_asset_types", "regulatory_frameworks", mode="before")
    @classmethod
    def validate_string_list_items(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for item in v:
            if not isinstance(item, str) or len(item) > 100:
                raise ValueError("List items must be strings of max 100 characters")
        return v


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str]
    source_type: str
    source_reference: Optional[str]
    incident_date: Optional[datetime]
    industry_vertical: Optional[str]
    initial_access_vector: Optional[str]
    mitre_techniques: Optional[List[str]]
    nist_controls: Optional[List[str]]
    regulatory_frameworks: Optional[List[str]]
    difficulty: str
    estimated_minutes: int
    status: str
    is_private: bool
    play_count: int
    avg_score: Optional[float]
    extraction_confidence: Optional[float]
    created_at: datetime


class ScenarioDetail(ScenarioOut):
    alert_sequence: Optional[Any]
    decision_tree: Optional[Any]
    pressure_injections: Optional[Any]
    debrief_skeleton: Optional[Any]
    compression_ratio: float
