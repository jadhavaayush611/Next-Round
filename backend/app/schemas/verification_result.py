import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.verification_result import VerificationOutcome, VerificationType
from app.schemas.evidence_item import EvidenceItemResponse

MAX_METHOD_VERSION_LENGTH = 100


class VerificationResultBase(BaseModel):
    """Base schema for verification result attributes."""

    candidate_claim_id: uuid.UUID | None = None
    evidence_source_id: uuid.UUID | None = None
    verification_type: VerificationType
    outcome: VerificationOutcome
    method_version: str
    explanation: str


class VerificationResultCreate(VerificationResultBase):
    """
    Internal payload for recording a verification check result and its evidence links.
    Validates target constraints, required methodology version and explanation,
    timezone-aware UTC execution timestamps, and distinct evidence item associations.
    """

    model_config = ConfigDict(extra="forbid")

    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence_item_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("method_version", mode="before")
    @classmethod
    def validate_method_version(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("method_version must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("method_version cannot be empty")
        if len(stripped) > MAX_METHOD_VERSION_LENGTH:
            raise ValueError(
                f"method_version cannot exceed {MAX_METHOD_VERSION_LENGTH} characters"
            )
        return stripped

    @field_validator("explanation", mode="before")
    @classmethod
    def validate_explanation(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("explanation must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("explanation cannot be empty")
        return stripped

    @field_validator("checked_at", mode="before")
    @classmethod
    def validate_checked_at(cls, v: Any) -> datetime:
        if v is None:
            return datetime.now(UTC)
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=UTC)
            return v.astimezone(UTC)
        raise ValueError("checked_at must be a valid datetime or ISO timestamp string")

    @field_validator("evidence_item_ids", mode="before")
    @classmethod
    def validate_evidence_item_ids(cls, v: Any) -> list[uuid.UUID]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("evidence_item_ids must be a list of UUIDs")
        parsed_ids: list[uuid.UUID] = []
        for item in v:
            if isinstance(item, uuid.UUID):
                parsed_ids.append(item)
            elif isinstance(item, str):
                parsed_ids.append(uuid.UUID(item))
            else:
                raise ValueError("evidence_item_ids must contain valid UUIDs")
        if len(parsed_ids) != len(set(parsed_ids)):
            raise ValueError("Duplicate evidence item associations are not permitted.")
        return parsed_ids

    @model_validator(mode="after")
    def validate_targets_and_type(self) -> "VerificationResultCreate":
        if self.candidate_claim_id is None and self.evidence_source_id is None:
            raise ValueError(
                "Verification result must reference at least one candidate_claim_id or evidence_source_id."
            )
        if (
            self.verification_type == VerificationType.CLAIM_SUPPORT
            and self.candidate_claim_id is None
        ):
            raise ValueError(
                "CLAIM_SUPPORT verification requires a candidate_claim_id."
            )
        return self


class VerificationResultResponse(BaseModel):
    """Validated read representation of a VerificationResult entity with linked evidence."""

    id: uuid.UUID
    candidate_claim_id: uuid.UUID | None
    evidence_source_id: uuid.UUID | None
    verification_type: VerificationType
    outcome: VerificationOutcome
    method_version: str
    explanation: str
    checked_at: datetime
    created_at: datetime
    evidence_item_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_items: list[EvidenceItemResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extract_evidence_data(cls, data: Any) -> Any:
        if hasattr(data, "evidence_items"):
            items = getattr(data, "evidence_items", []) or []
            return {
                "id": data.id,
                "candidate_claim_id": data.candidate_claim_id,
                "evidence_source_id": data.evidence_source_id,
                "verification_type": data.verification_type,
                "outcome": data.outcome,
                "method_version": data.method_version,
                "explanation": data.explanation,
                "checked_at": data.checked_at,
                "created_at": data.created_at,
                "evidence_item_ids": [item.id for item in items],
                "evidence_items": items,
            }
        return data

    @field_validator("checked_at", "created_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
