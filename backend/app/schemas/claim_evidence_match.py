import enum
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.candidate_claim import ClaimOrigin, ClaimType
from app.models.evidence_item import EvidenceType


class ClaimMatchStatus(enum.StrEnum):
    """Categorical matching result distinguishing match presence, absence, data sufficiency, and applicability."""

    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    NO_MATCH = "NO_MATCH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MatchingBasis(enum.StrEnum):
    """Deterministic rule or attribute category used to identify potential evidence relevance."""

    CANONICAL_SKILL_NAME = "CANONICAL_SKILL_NAME"
    SKILL_ALIAS = "SKILL_ALIAS"
    REPOSITORY_NAME = "REPOSITORY_NAME"
    REPOSITORY_DESCRIPTION = "REPOSITORY_DESCRIPTION"
    DOCUMENTATION_KEYWORD = "DOCUMENTATION_KEYWORD"


class EvidenceMatchItem(BaseModel):
    """Structured summary of a single evidence observation matching a candidate claim."""

    model_config = ConfigDict(from_attributes=True)

    evidence_item_id: uuid.UUID
    evidence_source_id: uuid.UUID
    evidence_type: EvidenceType
    source_locator: str | None = None
    matching_basis: MatchingBasis
    matched_term: str | None = None
    explanation: str = Field(..., max_length=500)


class ClaimEvidenceMatchResponse(BaseModel):
    """Complete claim-to-evidence matching report preserving claim provenance and explicit status."""

    model_config = ConfigDict(from_attributes=True)

    claim_id: uuid.UUID
    claim_type: ClaimType
    claim_text: str
    origin: ClaimOrigin
    canonical_path: str | None = None
    resume_parse_id: uuid.UUID | None = None
    status: ClaimMatchStatus
    summary: str
    matches: list[EvidenceMatchItem]
    total_matches: int
    sources_inspected: int
    items_inspected: int
    sources_summary: dict[str, int]
