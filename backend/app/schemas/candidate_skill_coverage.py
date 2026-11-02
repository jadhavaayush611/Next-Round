import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.candidate_claim import ClaimOrigin, ClaimType
from app.models.evidence_item import EvidenceType
from app.models.evidence_source import EvidenceSourceStatus, EvidenceSourceType
from app.models.verification_result import VerificationOutcome
from app.schemas.claim_evidence_match import EvidenceMatchItem


class CandidateSkillCoverageStatus(enum.StrEnum):
    """
    Deterministic categorical classifications for candidate skill coverage.
    Preserves auditability without aggregate readiness scores or inferred proficiency.
    """

    NO_EVIDENCE = "NO_EVIDENCE"
    UNVERIFIED_MATCHES = "UNVERIFIED_MATCHES"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    SUPPORTED_SOURCE_UNVERIFIED_CLAIM = "SUPPORTED_SOURCE_UNVERIFIED_CLAIM"
    CLAIM_SUPPORTED = "CLAIM_SUPPORTED"
    CLAIM_CONTRADICTED = "CLAIM_CONTRADICTED"
    CLAIM_INCONCLUSIVE = "CLAIM_INCONCLUSIVE"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    MIXED_VERIFICATION = "MIXED_VERIFICATION"


class ClaimProvenance(BaseModel):
    """Resume parse provenance reference for resume-derived claims."""

    model_config = ConfigDict(from_attributes=True)

    resume_parse_id: uuid.UUID
    canonical_path: str


class SkillClaimCoverageDetail(BaseModel):
    """Details of a candidate claim linked to a candidate skill."""

    model_config = ConfigDict(from_attributes=True)

    claim_id: uuid.UUID
    claim_text: str
    claim_type: ClaimType
    origin: ClaimOrigin
    provenance: ClaimProvenance | None = None
    latest_verification_outcome: VerificationOutcome | None = None
    latest_verification_result_id: uuid.UUID | None = None
    potential_matches_count: int = 0


class SkillEvidenceCoverageDetail(BaseModel):
    """Details of an evidence observation linked to a candidate skill."""

    model_config = ConfigDict(from_attributes=True)

    evidence_item_id: uuid.UUID
    evidence_source_id: uuid.UUID
    source_uri: str
    source_type: EvidenceSourceType
    source_status: EvidenceSourceStatus
    observed_at: datetime
    source_last_checked_at: datetime | None = None
    is_stale: bool | None = None
    evidence_type: EvidenceType
    description: str
    source_locator: str | None = None
    latest_verification_outcome: VerificationOutcome | None = None
    latest_verification_result_id: uuid.UUID | None = None


class ClaimScopeOutcome(BaseModel):
    """Latest evaluated verification determination for a claim scope."""

    model_config = ConfigDict(from_attributes=True)

    claim_id: uuid.UUID
    latest_outcome: VerificationOutcome
    verification_result_id: uuid.UUID
    method_version: str
    explanation: str
    checked_at: datetime


class SourceScopeOutcome(BaseModel):
    """Latest evaluated verification determination for a source scope."""

    model_config = ConfigDict(from_attributes=True)

    evidence_source_id: uuid.UUID
    source_uri: str
    source_type: EvidenceSourceType
    source_status: EvidenceSourceStatus
    latest_outcome: VerificationOutcome
    verification_result_id: uuid.UUID
    method_version: str
    explanation: str
    checked_at: datetime


class CandidateSkillCoverageItem(BaseModel):
    """Coverage determination and supporting records for a single candidate skill."""

    model_config = ConfigDict(from_attributes=True)

    candidate_skill_id: uuid.UUID
    skill_id: uuid.UUID
    canonical_name: str
    category: str
    coverage_status: CandidateSkillCoverageStatus
    summary: str
    claims: list[SkillClaimCoverageDetail] = Field(default_factory=list)
    active_evidence_items: list[SkillEvidenceCoverageDetail] = Field(
        default_factory=list
    )
    historical_unavailable_evidence: list[SkillEvidenceCoverageDetail] = Field(
        default_factory=list
    )
    potential_evidence_matches: list[EvidenceMatchItem] = Field(default_factory=list)
    claim_outcomes: list[ClaimScopeOutcome] = Field(default_factory=list)
    source_outcomes: list[SourceScopeOutcome] = Field(default_factory=list)


class UnassociatedSkillClaimDetail(BaseModel):
    """
    Candidate claim classified as SKILL that is not currently linked
    to any CandidateSkill association.
    """

    model_config = ConfigDict(from_attributes=True)

    claim_id: uuid.UUID
    claim_text: str
    origin: ClaimOrigin
    created_at: datetime
    provenance: ClaimProvenance | None = None


class CandidateSkillCoverageReport(BaseModel):
    """
    Paginated, candidate-scoped report of evidence-backed skill coverage,
    including status summary reconciling with total skills before pagination.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    generated_at: datetime
    total_skills_evaluated: int
    status_summary: dict[str, int]
    skills: list[CandidateSkillCoverageItem]
    unassociated_skill_claims: list[UnassociatedSkillClaimDetail] = Field(
        default_factory=list
    )
    unassociated_skill_claims_total: int = 0
