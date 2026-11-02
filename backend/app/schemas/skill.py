import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.skill_normalization import clean_aliases

MAX_CANONICAL_NAME_LENGTH = 100
MAX_CATEGORY_LENGTH = 100


class SkillBase(BaseModel):
    """Base schema for Skill attributes."""

    canonical_name: str
    category: str
    aliases: list[str] = Field(default_factory=list)


class SkillCreate(SkillBase):
    """Payload for creating a new canonical skill in the catalog."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("canonical_name", mode="before")
    @classmethod
    def validate_canonical_name(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("canonical_name must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("canonical_name cannot be empty")
        if len(stripped) > MAX_CANONICAL_NAME_LENGTH:
            raise ValueError(
                f"canonical_name cannot exceed {MAX_CANONICAL_NAME_LENGTH} characters"
            )
        return stripped

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("category must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("category cannot be empty")
        if len(stripped) > MAX_CATEGORY_LENGTH:
            raise ValueError(f"category cannot exceed {MAX_CATEGORY_LENGTH} characters")
        return stripped

    @field_validator("aliases", mode="before")
    @classmethod
    def validate_aliases(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("aliases must be a list of strings")
        cleaned = clean_aliases(v)
        return cleaned


class SkillUpdate(BaseModel):
    """Payload for updating an existing canonical skill."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str | None = None
    category: str | None = None
    aliases: list[str] | None = None

    @field_validator("canonical_name", mode="before")
    @classmethod
    def validate_canonical_name(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("canonical_name must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("canonical_name cannot be empty")
        if len(stripped) > MAX_CANONICAL_NAME_LENGTH:
            raise ValueError(
                f"canonical_name cannot exceed {MAX_CANONICAL_NAME_LENGTH} characters"
            )
        return stripped

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("category must be a string")
        stripped = " ".join(v.strip().split())
        if not stripped:
            raise ValueError("category cannot be empty")
        if len(stripped) > MAX_CATEGORY_LENGTH:
            raise ValueError(f"category cannot exceed {MAX_CATEGORY_LENGTH} characters")
        return stripped

    @field_validator("aliases", mode="before")
    @classmethod
    def validate_aliases(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("aliases must be a list of strings")
        return clean_aliases(v)


class SkillResponse(BaseModel):
    """Validated read representation of a Skill entity."""

    id: uuid.UUID
    canonical_name: str
    category: str
    aliases: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
