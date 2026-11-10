import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.competency import CompetencyDimension

MAX_IDENTIFIER_LENGTH = 100
MAX_NAME_LENGTH = 255


class CompetencyBase(BaseModel):
    """Core attributes for technical competency definitions."""

    identifier: str
    name: str
    description: str
    dimension: CompetencyDimension
    is_active: bool = True


class CompetencyCreate(CompetencyBase):
    """Payload for registering a new technical competency grounded in a canonical Skill."""

    model_config = ConfigDict(extra="forbid")

    skill_id: uuid.UUID

    @field_validator("identifier", mode="before")
    @classmethod
    def validate_identifier(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("identifier must be a string")
        stripped = "-".join(v.strip().lower().split())
        if not stripped:
            raise ValueError("identifier cannot be empty")
        if len(stripped) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(
                f"identifier cannot exceed {MAX_IDENTIFIER_LENGTH} characters"
            )
        return stripped

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("name must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("name cannot be empty")
        if len(stripped) > MAX_NAME_LENGTH:
            raise ValueError(f"name cannot exceed {MAX_NAME_LENGTH} characters")
        return stripped

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("description must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("description cannot be empty")
        return stripped


class CompetencyUpdate(BaseModel):
    """Payload for modifying an existing competency."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    dimension: CompetencyDimension | None = None
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("name must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("name cannot be empty")
        if len(stripped) > MAX_NAME_LENGTH:
            raise ValueError(f"name cannot exceed {MAX_NAME_LENGTH} characters")
        return stripped

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("description must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("description cannot be empty")
        return stripped


class CompetencyResponse(BaseModel):
    """Validated read representation of a Competency entity."""

    id: uuid.UUID
    skill_id: uuid.UUID
    identifier: str
    name: str
    description: str
    dimension: CompetencyDimension
    is_active: bool
    created_at: datetime
    updated_at: datetime
    skill_canonical_name: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class CompetencySummary(BaseModel):
    """Lightweight competency reference for task associations."""

    id: uuid.UUID
    identifier: str
    name: str
    dimension: CompetencyDimension
    skill_canonical_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
