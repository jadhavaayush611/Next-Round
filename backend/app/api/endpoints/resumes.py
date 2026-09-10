from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.resume import ResumeResponse
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
