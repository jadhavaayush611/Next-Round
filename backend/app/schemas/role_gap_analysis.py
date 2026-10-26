import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.role_requirement import RequirementImportance, RequirementType
from app.models.verification_result import VerificationOutcome


class GapAnalysisStatus(enum.StrEnum):
    """
    Deterministic categorical classifications for role-gap analysis on a requirement.
    Preserves distinctions between claim existence, evidence availability, verification outcomes,
    and demonstrated assessment results without artificial scoring or unsupported capability leaps.
    """

    UNRESOLVED_UNMAPPED = "UNRESOLVED_UNMAPPED"
    MISSING_RECORDED_COVERAGE = "MISSING_RECORDED_COVERAGE"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    UNAVAILABLE_EVIDENCE = "UNAVAILABLE_EVIDENCE"
    INCONCLUSIVE_VERIFICATION = "INCONCLUSIVE_VERIFICATION"
    CONTRADICTED_VERIFICATION = "CONTRADICTED_VERIFICATION"
    MIXED_VERIFICATION = "MIXED_VERIFICATION"
    MISSING_ASSESSMENT_EVIDENCE = "MISSING_ASSESSMENT_EVIDENCE"
    ASSESSMENT_PENDING_VERIFICATION = "ASSESSMENT_PENDING_VERIFICATION"
    SUPPORTED_EVIDENCE = "SUPPORTED_EVIDENCE"


class ScopeOutcome(BaseModel):
    """Latest evaluated verification determination for a specific candidate claim or evidence scope."""

    model_config = ConfigDict(from_attributes=True)

    scope_type: str  # 'claim', 'source', 'evidence_item'
    scope_id: uuid.UUID
    latest_outcome: VerificationOutcome | None = None
    verification_result_id: uuid.UUID | None = None
    method_version: str | None = None
    explanation: str | None = None


class SupportingRecords(BaseModel):
    """Traceable references to supporting domain records backing the gap analysis classification."""

    model_config = ConfigDict(from_attributes=True)

    candidate_skill_id: uuid.UUID | None = None
    candidate_claim_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_item_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_source_ids: list[uuid.UUID] = Field(default_factory=list)
    verification_result_ids: list[uuid.UUID] = Field(default_factory=list)


class RoleGapRequirementItem(BaseModel):
    """Gap analysis determination for a single role requirement on a target."""

    model_config = ConfigDict(from_attributes=True)

    requirement_id: uuid.UUID
    requirement_text: str
    requirement_type: RequirementType
    importance: RequirementImportance
    skill_id: uuid.UUID | None = None
    canonical_skill_name: str | None = None
    status: GapAnalysisStatus
    explanation: str
    supporting_records: SupportingRecords
    scope_outcomes: list[ScopeOutcome] = Field(default_factory=list)


class RoleGapAnalysisReport(BaseModel):
    """
    Structured, read-only role-gap analysis report for a candidate target.
    Preserves auditability and explicit classifications without percentages or scores.
    """

    model_config = ConfigDict(from_attributes=True)

    candidate_target_id: uuid.UUID
    role_title: str
    company: str | None = None
    total_requirements: int
    analyzed_at: datetime
    requirements: list[RoleGapRequirementItem]
    status_summary: dict[str, int]
