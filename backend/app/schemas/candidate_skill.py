import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.skill import SkillResponse


class CandidateSkillEvidenceBase(BaseModel):
    """Base schema for CandidateSkillEvidence join references."""

    candidate_claim_id: uuid.UUID | None = None
    evidence_item_id: uuid.UUID | None = None


class CandidateSkillEvidenceCreate(CandidateSkillEvidenceBase):
    """
    Payload for attaching a claim or evidence item provenance source to a CandidateSkill association.
    Enforces the domain invariant that exactly one provenance target is populated.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> "CandidateSkillEvidenceCreate":
        has_claim = self.candidate_claim_id is not None
        has_item = self.evidence_item_id is not None
        if not (has_claim ^ has_item):
            raise ValueError(
                "Candidate skill evidence must link to exactly one candidate_claim_id or evidence_item_id."
            )
        return self


class CandidateSkillEvidenceResponse(BaseModel):
    """Read representation of a CandidateSkillEvidence link."""

    id: uuid.UUID
    candidate_skill_id: uuid.UUID
    candidate_claim_id: uuid.UUID | None = None
    evidence_item_id: uuid.UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class CandidateSkillBase(BaseModel):
    """Base schema for CandidateSkill association."""

    skill_id: uuid.UUID


class CandidateSkillCreate(CandidateSkillBase):
    """
    Payload for creating a CandidateSkill association.
    Requires explicit provenance: at least one supporting claim or evidence item link
    must be provided, either via the `evidence` list or via top-level `candidate_claim_id` / `evidence_item_id`.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_claim_id: uuid.UUID | None = None
    evidence_item_id: uuid.UUID | None = None
    evidence: list[CandidateSkillEvidenceCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def consolidate_and_validate_sources(self) -> "CandidateSkillCreate":
        # Consolidate top-level claim/evidence_item if present
        if self.candidate_claim_id is not None or self.evidence_item_id is not None:
            top_link = CandidateSkillEvidenceCreate(
                candidate_claim_id=self.candidate_claim_id,
                evidence_item_id=self.evidence_item_id,
            )
            # Avoid duplicate in list
            if not any(
                e.candidate_claim_id == top_link.candidate_claim_id
                and e.evidence_item_id == top_link.evidence_item_id
                for e in self.evidence
            ):
                self.evidence.append(top_link)

        if not self.evidence:
            raise ValueError(
                "Candidate skill association requires at least one explicit claim or evidence item provenance link."
            )

        # Check for duplicate links within payload
        seen_claims: set[uuid.UUID] = set()
        seen_items: set[uuid.UUID] = set()
        for link in self.evidence:
            if link.candidate_claim_id is not None:
                if link.candidate_claim_id in seen_claims:
                    raise ValueError(
                        f"Duplicate candidate_claim_id '{link.candidate_claim_id}' in evidence links."
                    )
                seen_claims.add(link.candidate_claim_id)
            if link.evidence_item_id is not None:
                if link.evidence_item_id in seen_items:
                    raise ValueError(
                        f"Duplicate evidence_item_id '{link.evidence_item_id}' in evidence links."
                    )
                seen_items.add(link.evidence_item_id)

        return self


class CandidateSkillResponse(BaseModel):
    """Read representation of a CandidateSkill association."""

    id: uuid.UUID
    user_id: uuid.UUID
    skill_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    skill: SkillResponse | None = None
    evidence_links: list[CandidateSkillEvidenceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
