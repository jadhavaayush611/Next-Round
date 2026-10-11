import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.candidate_claim import ClaimOrigin, ClaimType
from app.models.user import User
from app.schemas.candidate_claim import (
    CandidateClaimCreate,
    CandidateClaimResponse,
)
from app.services.candidate_service import CandidateService

router = APIRouter()


@router.post(
    "",
    response_model=CandidateClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create candidate claim",
    description="Declares a placement claim. Enforces provenance rules: RESUME claims require parse snapshot and canonical path; USER_DECLARED claims forbid resume provenance.",
)
def create_candidate_claim(
    claim_in: CandidateClaimCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateClaimResponse:
    """Create and persist a candidate claim."""
    service = CandidateService(db)
    return service.create_claim(current_user, claim_in)


@router.get(
    "",
    response_model=list[CandidateClaimResponse],
    status_code=status.HTTP_200_OK,
    summary="List candidate claims",
    description="Lists all claims declared by or derived for the authenticated candidate.",
)
def list_candidate_claims(
    claim_type: ClaimType | None = Query(
        default=None, description="Filter by claim type"
    ),
    origin: ClaimOrigin | None = Query(
        default=None, description="Filter by claim origin"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CandidateClaimResponse]:
    """List claims for the authenticated user."""
    service = CandidateService(db)
    return service.list_claims(current_user, claim_type=claim_type, origin=origin)


@router.get(
    "/{claim_id}",
    response_model=CandidateClaimResponse,
    status_code=status.HTTP_200_OK,
    summary="Get candidate claim",
    description="Retrieves a specific candidate claim by ID, enforcing ownership.",
)
def get_candidate_claim(
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateClaimResponse:
    """Retrieve claim by ID."""
    service = CandidateService(db)
    return service.get_claim(current_user, claim_id)
