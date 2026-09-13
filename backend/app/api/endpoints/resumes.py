import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.resume import ResumeResponse
from app.schemas.resume_parse import (
    CanonicalResumeResponse,
    ResumeParseResponse,
)
from app.services.parse_service import ResumeParseService
from app.services.resume import ResumeService

router = APIRouter()


@router.post(
    "",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a candidate resume",
    description="Accepts a PDF or DOCX file, validates file signature, stores securely, and returns metadata.",
)
def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeResponse:
    """
    Upload and persist a new candidate resume.
    Ensures safe storage, ownership isolation, signature verification, and automatic version increment.
    """
    resume_service = ResumeService(db)
    resume = resume_service.upload_resume(current_user, file)
    return ResumeResponse.model_validate(resume)


@router.post(
    "/{resume_id}/parse",
    response_model=ResumeParseResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse a candidate resume",
    description="Synchronously extracts, semantically parses, and persists an immutable canonical snapshot for the requested resume.",
)
def parse_resume(
    resume_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeParseResponse:
    """
    Synchronously triggers semantic parsing of a specific resume.
    Validates ownership, guarantees idempotency across identical parser/schema versions,
    and returns the resulting parse snapshot.
    """
    parse_service = ResumeParseService(db)
    parse_record = parse_service.parse_resume(current_user, resume_id)
    return ResumeParseResponse.model_validate(parse_record)


@router.get(
    "/{resume_id}/canonical",
    response_model=CanonicalResumeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest canonical resume representation",
    description="Retrieves the latest successful canonical resume snapshot for the requested resume.",
)
def get_canonical_resume(
    resume_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonicalResumeResponse:
    """
    Fetches the latest successful canonical representation of an authenticated user's resume.
    """
    parse_service = ResumeParseService(db)
    return parse_service.get_latest_canonical(current_user, resume_id)
