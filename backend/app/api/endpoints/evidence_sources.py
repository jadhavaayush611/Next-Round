import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.evidence_source import EvidenceSourceStatus, EvidenceSourceType
from app.models.user import User
from app.schemas.evidence_source import (
    EvidenceCollectionResponse,
    EvidenceSourceCreate,
    EvidenceSourceResponse,
    EvidenceSourceStatusUpdate,
)
from app.services.evidence_source_service import EvidenceSourceService
from app.services.github_client import GitHubClient
from app.services.github_evidence_collector import GitHubEvidenceCollectorService

router = APIRouter()


def get_github_client() -> GitHubClient:
    """Dependency provider for GitHub API client."""
    return GitHubClient()


@router.post(
    "",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register evidence source",
    description="Registers an external evidence source (repository, profile, portfolio). Validates and normalizes URLs without network lookups. Initializes access status to NOT_CHECKED.",
)
def register_evidence_source(
    source_in: EvidenceSourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceSourceResponse:
    """Register a new external evidence source for the authenticated candidate."""
    service = EvidenceSourceService(db)
    return service.register_source(current_user, source_in)


@router.get(
    "",
    response_model=list[EvidenceSourceResponse],
    status_code=status.HTTP_200_OK,
    summary="List evidence sources",
    description="Lists all external evidence sources registered by the authenticated candidate, with optional source-type and status filters.",
)
def list_evidence_sources(
    source_type: EvidenceSourceType | None = Query(
        default=None, description="Filter by evidence source type"
    ),
    access_status: EvidenceSourceStatus | None = Query(
        default=None, description="Filter by access status"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EvidenceSourceResponse]:
    """List evidence sources owned by the authenticated candidate."""
    service = EvidenceSourceService(db)
    return service.list_sources(
        current_user, source_type=source_type, access_status=access_status
    )


@router.get(
    "/{source_id}",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get evidence source",
    description="Retrieves a specific evidence source by ID, enforcing candidate ownership.",
)
def get_evidence_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceSourceResponse:
    """Fetch an evidence source by ID."""
    service = EvidenceSourceService(db)
    return service.get_source(current_user, source_id)


@router.patch(
    "/{source_id}",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update evidence source status",
    description="Controlled lifecycle update. Candidates may only revoke access (access_status=REVOKED). Verification statuses cannot be set directly.",
)
def update_evidence_source_status(
    source_id: uuid.UUID,
    status_in: EvidenceSourceStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceSourceResponse:
    """Update evidence source status (revocation only)."""
    service = EvidenceSourceService(db)
    return service.update_status(current_user, source_id, status_in)


@router.patch(
    "/{source_id}/revoke",
    response_model=EvidenceSourceResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke evidence source access",
    description="Revokes access to a registered evidence source, preventing future retrieval while preserving historical traceability.",
)
def revoke_evidence_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceSourceResponse:
    """Revoke authorization to an evidence source."""
    service = EvidenceSourceService(db)
    return service.revoke_source(current_user, source_id)


@router.post(
    "/{source_id}/collect",
    response_model=EvidenceCollectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Collect evidence from GitHub repository",
    description="Collects repository metadata and README documentation observations from a registered public GitHub repository without mutating claims or generating verification conclusions.",
)
def collect_evidence_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    github_client: GitHubClient = Depends(get_github_client),
) -> EvidenceCollectionResponse:
    """Collect evidence observations from a registered public GitHub repository."""
    collector = GitHubEvidenceCollectorService(db, github_client=github_client)
    return collector.collect_repository_evidence(current_user, source_id)
