import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class CandidateTargetBase(BaseModel):
    role_title: str
    company: str | None = None
    job_description: str | None = None


class CandidateTargetCreate(CandidateTargetBase):
    is_active: bool = True

    @field_validator("role_title", mode="before")
    @classmethod
    def validate_role_title(cls, v: Any) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Role title cannot be empty")
            return stripped
        raise ValueError("Role title must be a string")

    @field_validator("company", "job_description", mode="before")
    @classmethod
    def sanitize_optional_text(cls, v: Any) -> str | None:
        if v is not None:
            if isinstance(v, str):
                stripped = v.strip()
                return stripped if stripped else None
            raise ValueError("Field must be a string or null")
        return None


class CandidateTargetResponse(CandidateTargetBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_profile_id: uuid.UUID
    is_active: bool
    created_at: datetime
