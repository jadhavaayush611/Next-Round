from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.candidate_intelligence import (
    CandidateIntelligenceOverviewResponse,
)
from app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileResponse,
    CandidateProfileUpdate,
)
from app.services.candidate_intelligence_service import (
    CandidateIntelligenceService,
)
from app.services.candidate_service import CandidateService

router = APIRouter()


@router.get(
    "/intelligence-overview",
    response_model=CandidateIntelligenceOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get candidate intelligence overview",
    description="Integrates candidate profile context, active target alignment, evidence-backed skill coverage, resume provenance, and connected evidence sources into a consolidated, deterministic read-only view.",
)
def get_candidate_intelligence_overview(
    freshness_threshold_days: int | None = Query(
        default=None,
        ge=1,
        description="Optional freshness threshold in days to flag observations older than threshold",
    ),
    skills_preview_limit: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of skills to include in the preview slice",
    ),
    skills_preview_offset: int = Query(
        default=0,
        ge=0,
        description="Offset for the skills preview slice",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateIntelligenceOverviewResponse:
    """Fetch consolidated, candidate-scoped intelligence overview."""
    service = CandidateIntelligenceService(db)
    return service.get_intelligence_overview(
        user=current_user,
        freshness_threshold_days=freshness_threshold_days,
        skills_preview_limit=skills_preview_limit,
        skills_preview_offset=skills_preview_offset,
    )


@router.get(
    "",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current candidate profile",
    description="Retrieves the authenticated candidate's placement profile and active target configuration.",
)
@router.get(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_current_candidate_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateProfileResponse:
    """Fetch candidate profile for the authenticated user."""
    service = CandidateService(db)
    return service.get_profile_response(current_user)


@router.post(
    "",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create candidate profile",
    description="Creates a new placement profile for the authenticated candidate. Enforces 1:1 relationship with User.",
)
@router.post(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_candidate_profile(
    profile_in: CandidateProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateProfileResponse:
    """Create a candidate profile for the authenticated user."""
    service = CandidateService(db)
    return service.create_profile(current_user, profile_in)


@router.patch(
    "",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Update candidate profile",
    description="Updates editable placement fields (preferred_locations, graduation_year) for the authenticated candidate.",
)
@router.patch(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def update_candidate_profile(
    profile_in: CandidateProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateProfileResponse:
    """Update candidate profile for the authenticated user."""
    service = CandidateService(db)
    return service.update_profile(current_user, profile_in)
