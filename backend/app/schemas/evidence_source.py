import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.evidence_source import (
    AccessMode,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.utils.url_validator import normalize_and_validate_url


class EvidenceSourceBase(BaseModel):
    """Base schema for evidence source attributes."""

    source_type: EvidenceSourceType
    source_uri: str
    access_mode: AccessMode = AccessMode.PUBLIC


class EvidenceSourceCreate(EvidenceSourceBase):
    """
    Payload for candidate evidence source registration.
    URL is validated and normalized. Verification status cannot be forged.
    """

    @field_validator("source_uri")
    @classmethod
    def validate_url(cls, v: str) -> str:
        # Pre-validate URL syntax, scheme, credentials, and host safety
        return normalize_and_validate_url(v)

    @model_validator(mode="after")
    def validate_source_uri_against_type(self) -> "EvidenceSourceCreate":
        # Validate source-type specific rules and normalize accordingly
        self.source_uri = normalize_and_validate_url(self.source_uri, self.source_type)
        return self


class EvidenceSourceStatusUpdate(BaseModel):
    """
    Payload for candidate lifecycle update.
    Candidates can only revoke access; verification results cannot be asserted by clients.
    """

    access_status: EvidenceSourceStatus

    @field_validator("access_status")
    @classmethod
    def ensure_only_revocation_allowed(
        cls, v: EvidenceSourceStatus
    ) -> EvidenceSourceStatus:
        if v != EvidenceSourceStatus.REVOKED:
            raise ValueError(
                "Candidates may only revoke access to a source; verification statuses cannot be set directly."
            )
        return v


class EvidenceSourceResponse(BaseModel):
    """Safe, validated public response model for an EvidenceSource entity."""

    id: uuid.UUID
    user_id: uuid.UUID
    source_type: EvidenceSourceType
    source_uri: str
    access_mode: AccessMode
    access_status: EvidenceSourceStatus
    last_checked_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceCollectionResponse(BaseModel):
    """
    Validated response summarizing the outcome and observation counts of an
    evidence collection run for an EvidenceSource.
    """

    model_config = ConfigDict(from_attributes=True)

    evidence_source_id: uuid.UUID
    source_uri: str
    access_status: EvidenceSourceStatus
    items_collected: int
    items_retained: int
    total_items: int
    collected_at: datetime
    message: str
    item_ids: list[uuid.UUID] = Field(default_factory=list)
