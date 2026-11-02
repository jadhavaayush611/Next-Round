import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.evidence_item import EvidenceType

# Maximum allowed size for minimal structured observations in bytes (64 KB)
MAX_OBSERVED_DATA_BYTES = 65536
MAX_LOCATOR_LENGTH = 2048


class EvidenceItemBase(BaseModel):
    """Base schema for observation attributes."""

    evidence_source_id: uuid.UUID
    evidence_type: EvidenceType
    description: str
    observed_data: dict[str, Any] | None = None
    source_locator: str | None = None


class EvidenceItemCreate(EvidenceItemBase):
    """
    Internal payload for recording a specific observation obtained from an evidence source.
    Validates required description, stable enum classification, minimal structured facts,
    and timezone-aware UTC observation timestamps.
    """

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Description must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("Description cannot be empty")
        return stripped

    @field_validator("source_locator", mode="before")
    @classmethod
    def validate_source_locator(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("source_locator must be a string or null")
        stripped = v.strip()
        if not stripped:
            return None
        if len(stripped) > MAX_LOCATOR_LENGTH:
            raise ValueError(
                f"source_locator must not exceed {MAX_LOCATOR_LENGTH} characters"
            )
        return stripped

    @field_validator("observed_data")
    @classmethod
    def validate_observed_data(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("observed_data must be a dictionary or null")

        # Invariant: Keep structured observations minimal; do not copy entire repositories or profiles
        try:
            serialized = json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observed_data must be JSON-serializable: {exc}") from exc

        if len(serialized.encode("utf-8")) > MAX_OBSERVED_DATA_BYTES:
            raise ValueError(
                f"observed_data payload exceeds maximum allowed size ({MAX_OBSERVED_DATA_BYTES} bytes). "
                "Observations must remain minimal structured facts."
            )
        return v

    @field_validator("observed_at", mode="before")
    @classmethod
    def validate_observed_at(cls, v: Any) -> datetime:
        if v is None:
            return datetime.now(UTC)
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=UTC)
            return v.astimezone(UTC)
        raise ValueError("observed_at must be a valid datetime or ISO timestamp string")


class EvidenceItemResponse(BaseModel):
    """Validated read representation of an EvidenceItem entity."""

    id: uuid.UUID
    evidence_source_id: uuid.UUID
    evidence_type: EvidenceType
    description: str
    observed_data: dict[str, Any] | None = None
    source_locator: str | None = None
    observed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("observed_at", "created_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
