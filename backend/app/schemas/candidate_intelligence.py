import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.evidence_source import EvidenceSourceStatus, EvidenceSourceType
from app.models.resume_parse import ParseStatus
from app.models.role_requirement import RequirementImportance, RequirementType
from app.schemas.candidate_skill_coverage import CandidateSkillCoverageStatus
from app.schemas.role_gap_analysis import GapAnalysisStatus


class TargetSummary(BaseModel):
    """Structured summary of a candidate's active target role configuration."""

    model_config = ConfigDict(from_attributes=True)

    target_id: uuid.UUID
    role_title: str
    company: str | None = None
    created_at: datetime


class ProfileSummary(BaseModel):
    """Structured summary of a candidate's placement profile and active target context."""

    model_config = ConfigDict(from_attributes=True)

    profile_id: uuid.UUID
    graduation_year: int | None = None
    preferred_locations: list[str] | None = None
    has_active_target: bool
    active_target: TargetSummary | None = None


class ResumeProvenanceSummary(BaseModel):
    """
    Structured summary of resume parsing state and candidate claim origin partitions.
    Preserves auditability without conflating latest uploaded resume with latest parsed snapshot.
    """

    model_config = ConfigDict(from_attributes=True)

    latest_resume_id: uuid.UUID
    latest_resume_version: int
    latest_parse_id: uuid.UUID | None = None
    parse_status: ParseStatus | None = None
    parsed_at: datetime | None = None

    # Full candidate population claim origin partitions
    total_claims_recorded: int
    resume_derived_claims_count: int
    user_declared_claims_count: int
    claims_from_latest_parse_count: int


class EvidenceSourceOverviewItem(BaseModel):
    """
    Sanitized summary of an individual registered evidence source.
    Avoids leaking arbitrary raw URLs, credentials, query parameters, or internal paths.
    """

    model_config = ConfigDict(from_attributes=True)

    source_id: uuid.UUID
    source_type: EvidenceSourceType
    source_host: str
    source_path: str
    access_status: EvidenceSourceStatus
    last_checked_at: datetime | None = None


class EvidenceSourcesOverview(BaseModel):
    """
    Overview of connected evidence sources for the candidate.
    Summary counts cover the complete candidate source population independently of preview limits.
    """

    model_config = ConfigDict(from_attributes=True)

    total_sources: int
    available_sources_count: int
    non_available_sources_count: int
    sources: list[EvidenceSourceOverviewItem] = Field(default_factory=list)


class SkillPreviewItem(BaseModel):
    """
    Evidence-backed coverage summary for a single candidate skill in the preview slice.
    Correlates target requirements strictly via canonical skill IDs without altering status.
    """

    model_config = ConfigDict(from_attributes=True)

    candidate_skill_id: uuid.UUID
    skill_id: uuid.UUID
    canonical_name: str
    category: str
    coverage_status: CandidateSkillCoverageStatus
    summary: str
    is_required_by_active_target: bool


class SkillCoverageOverview(BaseModel):
    """
    Full-population metrics and bounded preview slice of evidence-backed skill coverage.
    Status summary covers 100% of candidate skills prior to preview pagination.
    """

    model_config = ConfigDict(from_attributes=True)

    total_skills_evaluated: int
    status_summary: dict[str, int]
    unassociated_skill_claims_total: int

    # Bounded preview pagination metadata
    preview_limit: int
    preview_offset: int
    preview_count: int
    skills_preview: list[SkillPreviewItem] = Field(default_factory=list)


class TargetRequirementAlignmentItem(BaseModel):
    """
    Alignment determination of a target requirement against candidate skills and evidence.
    Unmapped requirements remain unmapped without forced synthetic IDs.
    """

    model_config = ConfigDict(from_attributes=True)

    requirement_id: uuid.UUID
    requirement_text: str
    requirement_type: RequirementType
    importance: RequirementImportance
    skill_id: uuid.UUID | None = None
    canonical_skill_name: str | None = None
    gap_status: GapAnalysisStatus
    explanation: str


class TargetAlignmentOverview(BaseModel):
    """
    Overview of target role requirements and gap analysis for the active candidate target.
    """

    model_config = ConfigDict(from_attributes=True)

    target_id: uuid.UUID
    role_title: str
    company: str | None = None
    total_requirements: int
    gap_status_summary: dict[str, int]
    requirements: list[TargetRequirementAlignmentItem] = Field(default_factory=list)


class CandidateIntelligenceOverviewResponse(BaseModel):
    """
    Deterministic, candidate-scoped, read-only intelligence integration report.
    Consolidates profile, target, resume provenance, sources, skill coverage, and target alignment.
    Disclaims all inferred proficiency and readiness scoring.
    """

    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    profile: ProfileSummary | None = None
    resume_provenance: ResumeProvenanceSummary | None = None
    evidence_sources: EvidenceSourcesOverview
    skill_coverage: SkillCoverageOverview
    target_alignment: TargetAlignmentOverview | None = None
    audit_disclaimers: list[str] = Field(default_factory=list)
