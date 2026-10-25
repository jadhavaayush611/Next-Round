import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
)


class RoleRequirementBase(BaseModel):
    """Base schema for a role requirement."""

    skill_id: uuid.UUID | None = None
    requirement_text: str
    requirement_type: RequirementType
    importance: RequirementImportance
    source_type: RequirementSourceType

    @field_validator("requirement_text", mode="before")
    @classmethod
    def validate_requirement_text(cls, v: Any) -> str:
        """Preserve exact original text without mutation while rejecting empty or whitespace-only input."""
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("Requirement text cannot be empty or whitespace-only.")
            return v
        raise ValueError("Requirement text must be a string.")


class RoleRequirementCreate(RoleRequirementBase):
    """Payload to create a role requirement for a candidate target."""

    pass


class RoleRequirementResponse(RoleRequirementBase):
    """API response schema for a role requirement."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_target_id: uuid.UUID
    created_at: datetime
