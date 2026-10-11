import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.candidate_target import (
    CandidateTargetCreate,
    CandidateTargetResponse,
)
from app.services.candidate_service import CandidateService

router = APIRouter()


@router.post(
    "",
    response_model=CandidateTargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create candidate target",
    description="Creates a new target role/company configuration. If marked active, automatically deactivates prior targets to preserve historical context.",
)
def create_candidate_target(
    target_in: CandidateTargetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateTargetResponse:
    """Create a new candidate target for the authenticated candidate."""
    service = CandidateService(db)
    return service.create_target(current_user, target_in)


@router.get(
    "",
    response_model=list[CandidateTargetResponse],
    status_code=status.HTTP_200_OK,
    summary="List candidate targets",
    description="Lists all current and historical targets configured for the authenticated candidate.",
)
def list_candidate_targets(
    active_only: bool = Query(
        default=False, description="Filter for active target only"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CandidateTargetResponse]:
    """List targets for the authenticated candidate."""
    service = CandidateService(db)
    return service.list_targets(current_user, active_only=active_only)


@router.get(
    "/active",
    response_model=CandidateTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active candidate target",
    description="Retrieves the currently active target configuration for the candidate.",
)
def get_active_candidate_target(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateTargetResponse:
    """Fetch the single active target for the authenticated candidate."""
    service = CandidateService(db)
    return service.get_active_target(current_user)


@router.patch(
    "/{target_id}/activate",
    response_model=CandidateTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate candidate target",
    description="Activates a historical target and deactivates any other active target.",
)
def activate_candidate_target(
    target_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateTargetResponse:
    """Activate target by ID."""
    service = CandidateService(db)
    return service.activate_target(current_user, target_id)


@router.patch(
    "/{target_id}/deactivate",
    response_model=CandidateTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate candidate target",
    description="Deactivates a candidate target, leaving the profile with no active target.",
)
def deactivate_candidate_target(
    target_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateTargetResponse:
    """Deactivate target by ID."""
    service = CandidateService(db)
    return service.deactivate_target(current_user, target_id)
