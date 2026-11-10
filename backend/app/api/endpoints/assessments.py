import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.assessment_definition import (
    AssessmentDifficulty,
    AssessmentType,
)
from app.models.user import User
from app.schemas.assessment import (
    AssessmentCatalogItemResponse,
    AssessmentDetailResponse,
)
from app.services.assessment_catalog_service import (
    AssessmentCatalogService,
    AssessmentNotFoundError,
)

router = APIRouter()


@router.get(
    "",
    response_model=list[AssessmentCatalogItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List published assessments",
    description="Lists candidate-accessible published assessments resolving strictly to each assessment's latest published revision. Excludes drafts and deprecated versions.",
)
def list_assessments(
    response: Response,
    assessment_type: AssessmentType | None = Query(
        default=None, description="Filter by assessment type"
    ),
    difficulty: AssessmentDifficulty | None = Query(
        default=None, description="Filter by difficulty level"
    ),
    skill_id: uuid.UUID | None = Query(
        default=None,
        description="Filter assessments covering a specific canonical skill",
    ),
    search: str | None = Query(
        default=None,
        description="Text search against assessment title and description",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of assessments to return",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of assessments to skip for pagination",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssessmentCatalogItemResponse]:
    """List published assessments with filtering, search, and pagination."""
    service = AssessmentCatalogService(db)
    items, total = service.list_published_assessments(
        assessment_type=assessment_type,
        difficulty=difficulty,
        skill_id=skill_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/{assessment_id}",
    response_model=AssessmentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get published assessment detail",
    description="Retrieves a specific published assessment by ID or stable identifier. Tasks contain only candidate-visible prompts and fixtures; evaluator rubrics and solutions are strictly omitted.",
)
def get_assessment(
    assessment_id: str,
    version: int | None = Query(
        default=None,
        ge=1,
        description="Optional explicit version number; defaults to latest published",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentDetailResponse:
    """Fetch published assessment detail with candidate-safe tasks."""
    service = AssessmentCatalogService(db)
    try:
        return service.get_published_assessment(assessment_id, version=version)
    except AssessmentNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment '{assessment_id}' not found.",
        ) from err
