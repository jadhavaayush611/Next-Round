import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.resume_parse import ParseStatus
from app.schemas.canonical_resume import CanonicalResume


class ResumeParseResponse(BaseModel):
    """API response model for a resume parse snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID
    resume_version: int
    parser_version: str
    schema_version: str
    status: ParseStatus
    canonical_data: CanonicalResume | None = None
    extraction_metadata: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class CanonicalResumeResponse(BaseModel):
    """API response model for the latest successful canonical resume snapshot."""

    model_config = ConfigDict(from_attributes=True)

    resume_id: uuid.UUID
    resume_version: int
    parser_version: str
    schema_version: str
    created_at: datetime
    canonical_resume: CanonicalResume
