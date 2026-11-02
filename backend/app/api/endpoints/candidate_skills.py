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
from app.schemas.candidate_skill_coverage import (
    CandidateSkillCoverageItem,
    CandidateSkillCoverageReport,
)
from app.services.candidate_skill_coverage_service import (
    CandidateSkillCoverageService,
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
    "/coverage",
    response_model=CandidateSkillCoverageReport,
    status_code=status.HTTP_200_OK,
    summary="Get candidate skill coverage report",
    description="Generates an evidence-backed skill coverage report for the authenticated candidate, with pagination and unassociated claim inspection.",
)
def get_candidate_skill_coverage_report(
    skill_id: uuid.UUID | None = Query(
        default=None, description="Optional canonical skill ID filter"
    ),
    limit: int = Query(
        default=50, ge=1, le=100, description="Page limit for candidate skills"
    ),
    offset: int = Query(default=0, ge=0, description="Offset for candidate skills"),
    freshness_threshold_days: int | None = Query(
        default=None,
        ge=1,
        description="Optional freshness threshold in days to flag observations older than threshold",
    ),
    unassociated_claims_limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Page limit for unassociated skill claims",
    ),
    unassociated_claims_offset: int = Query(
        default=0,
        ge=0,
        description="Offset for unassociated skill claims",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSkillCoverageReport:
    """Fetch paginated candidate skill coverage report."""
    service = CandidateSkillCoverageService(db)
    return service.get_coverage_report(
        user=current_user,
        skill_id=skill_id,
        limit=limit,
        offset=offset,
        freshness_threshold_days=freshness_threshold_days,
        unassociated_claims_limit=unassociated_claims_limit,
        unassociated_claims_offset=unassociated_claims_offset,
    )


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
    "/{candidate_skill_id}/coverage",
    response_model=CandidateSkillCoverageItem,
    status_code=status.HTTP_200_OK,
    summary="Get individual candidate skill coverage",
    description="Retrieves evidence-backed coverage determination and supporting records for a specific candidate skill.",
)
def get_candidate_skill_coverage(
    candidate_skill_id: uuid.UUID,
    freshness_threshold_days: int | None = Query(
        default=None,
        ge=1,
        description="Optional freshness threshold in days to flag observations older than threshold",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSkillCoverageItem:
    """Fetch individual candidate skill coverage by candidate skill ID."""
    service = CandidateSkillCoverageService(db)
    return service.get_skill_coverage(
        user=current_user,
        candidate_skill_id=candidate_skill_id,
        freshness_threshold_days=freshness_threshold_days,
    )


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
