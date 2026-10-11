import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.candidate_claim import ClaimOrigin, ClaimType

# RFC 6901 JSON pointer pattern: starts with / followed by zero or more segments
JSON_POINTER_REGEX = re.compile(r"^(/([^/~]|~[01])*)+$")


class CandidateClaimBase(BaseModel):
    claim_type: ClaimType
    claim_text: str
    origin: ClaimOrigin


class CandidateClaimCreate(CandidateClaimBase):
    resume_parse_id: uuid.UUID | None = None
    canonical_path: str | None = None

    @field_validator("claim_text", mode="before")
    @classmethod
    def validate_claim_text(cls, v: Any) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Claim text cannot be empty")
            return stripped
        raise ValueError("Claim text must be a string")

    @field_validator("canonical_path", mode="before")
    @classmethod
    def validate_canonical_path_format(cls, v: Any) -> str | None:
        if v is not None:
            if isinstance(v, str):
                stripped = v.strip()
                if not stripped:
                    return None
                if not stripped.startswith("/"):
                    raise ValueError(
                        "canonical_path must follow JSON Pointer syntax starting with '/'"
                    )
                if not JSON_POINTER_REGEX.match(stripped):
                    raise ValueError(
                        "canonical_path contains invalid JSON Pointer syntax"
                    )
                return stripped
            raise ValueError("canonical_path must be a string or null")
        return None

    @model_validator(mode="after")
    def validate_provenance_invariants(self) -> "CandidateClaimCreate":
        if self.origin == ClaimOrigin.RESUME:
            if not self.resume_parse_id:
                raise ValueError(
                    "Resume-derived claims require resume_parse_id referencing the parse snapshot"
                )
            if not self.canonical_path:
                raise ValueError(
                    "Resume-derived claims require canonical_path referencing the JSON snapshot location"
                )
        elif self.origin == ClaimOrigin.USER_DECLARED:
            if self.resume_parse_id is not None or self.canonical_path is not None:
                raise ValueError(
                    "User-declared claims must not provide resume_parse_id or canonical_path"
                )
        return self


class CandidateClaimResponse(CandidateClaimBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    resume_parse_id: uuid.UUID | None = None
    canonical_path: str | None = None
    created_at: datetime
