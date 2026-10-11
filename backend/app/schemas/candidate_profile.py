import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.candidate_target import CandidateTargetResponse

PROFILE_IMMUTABLE_FIELDS = {
    "id",
    "user_id",
    "created_at",
    "updated_at",
}


class CandidateProfileBase(BaseModel):
    preferred_locations: list[str] | None = None
    graduation_year: int | None = None

    @field_validator("preferred_locations", mode="before")
    @classmethod
    def validate_preferred_locations(cls, v: Any) -> list[str] | None:
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("preferred_locations must be a list of strings")
            cleaned: list[str] = []
            for item in v:
                if not isinstance(item, str):
                    raise ValueError("All location entries must be strings")
                stripped = item.strip()
                if not stripped:
                    raise ValueError("Location entries cannot be empty")
                cleaned.append(stripped)
            return cleaned
        return None

    @field_validator("graduation_year", mode="before")
    @classmethod
    def validate_graduation_year(cls, v: Any) -> int | None:
        if v is not None:
            try:
                year = int(v)
            except (ValueError, TypeError):
                raise ValueError("graduation_year must be a valid integer") from None
            if year < 1950 or year > 2100:
                raise ValueError(
                    "graduation_year must be within a defensible calendar range (1950-2100)"
                )
            return year
        return None


class CandidateProfileCreate(CandidateProfileBase):
    pass


class CandidateProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_locations: list[str] | None = None
    graduation_year: int | None = None

    @model_validator(mode="before")
    @classmethod
    def check_immutable_and_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Invalid payload format")

        immutable_found = [f for f in data if f in PROFILE_IMMUTABLE_FIELDS]
        if immutable_found:
            raise ValueError(
                f"Fields {', '.join(sorted(immutable_found))} are immutable and cannot be updated"
            )

        editable_provided = {
            k: v
            for k, v in data.items()
            if k in {"preferred_locations", "graduation_year"}
        }
        if not editable_provided:
            raise ValueError(
                "Update payload cannot be empty. At least one field must be provided."
            )

        return data

    @field_validator("preferred_locations", mode="before")
    @classmethod
    def validate_preferred_locations(cls, v: Any) -> list[str] | None:
        return CandidateProfileBase.validate_preferred_locations(v)

    @field_validator("graduation_year", mode="before")
    @classmethod
    def validate_graduation_year(cls, v: Any) -> int | None:
        return CandidateProfileBase.validate_graduation_year(v)


class CandidateProfileResponse(CandidateProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    active_target: CandidateTargetResponse | None = None
