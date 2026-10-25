import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.candidate_skill import (
    CandidateSkillCreate,
    CandidateSkillEvidenceCreate,
    CandidateSkillResponse,
)
from app.services.candidate_skill_service import CandidateSkillService

router = APIRouter()


@router.post(
    "",
    response_model=CandidateSkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create candidate skill association",
    description="Associates the authenticated candidate with a canonical skill from the catalog, requiring explicit claim or evidence item provenance.",
)
def create_candidate_skill(
    skill_in: CandidateSkillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSkillResponse:
    """Create a new candidate skill association with explicit provenance."""
    service = CandidateSkillService(db)
    return service.create_candidate_skill(current_user, skill_in)


@router.get(
    "",
    response_model=list[CandidateSkillResponse],
    status_code=status.HTTP_200_OK,
    summary="List candidate skills",
    description="Lists all skill associations declared for the authenticated candidate, with optional canonical skill ID filtering.",
)
def list_candidate_skills(
    skill_id: uuid.UUID | None = Query(
        default=None, description="Filter by canonical skill ID"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CandidateSkillResponse]:
    """List skill associations for the authenticated candidate."""
    service = CandidateSkillService(db)
    return service.list_candidate_skills(current_user, skill_id=skill_id)


@router.get(
    "/{candidate_skill_id}",
    response_model=CandidateSkillResponse,
    status_code=status.HTTP_200_OK,
    summary="Get candidate skill association",
    description="Retrieves a specific candidate skill association by ID, enforcing ownership.",
)
def get_candidate_skill(
    candidate_skill_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSkillResponse:
    """Fetch candidate skill by ID."""
    service = CandidateSkillService(db)
    return service.get_candidate_skill(current_user, candidate_skill_id)


@router.post(
    "/{candidate_skill_id}/evidence",
    response_model=CandidateSkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach evidence or claim to candidate skill",
    description="Attaches an additional claim or evidence item provenance source to an existing candidate skill association.",
)
def add_candidate_skill_evidence(
    candidate_skill_id: uuid.UUID,
    evidence_in: CandidateSkillEvidenceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSkillResponse:
    """Attach evidence or claim to an existing candidate skill association."""
    service = CandidateSkillService(db)
    return service.add_evidence_link(current_user, candidate_skill_id, evidence_in)


@router.delete(
    "/{candidate_skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete candidate skill association",
    description="Deletes a candidate skill association owned by the candidate without mutating underlying claims or evidence items.",
)
def delete_candidate_skill(
    candidate_skill_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete candidate skill association by ID."""
    service = CandidateSkillService(db)
    service.delete_candidate_skill(current_user, candidate_skill_id)
