import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.evidence_source import (
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.user import User
from app.repositories.evidence_source import EvidenceSourceRepository
from app.schemas.evidence_source import (
    EvidenceSourceCreate,
    EvidenceSourceResponse,
    EvidenceSourceStatusUpdate,
)
from app.utils.url_validator import normalize_and_validate_url


class EvidenceSourceService:
    """
    Domain service for managing external evidence sources.
    Enforces URL validation/normalization, server-governed lifecycle status,
    candidate ownership, and anti-forgery rules.
    """

    def __init__(self, db: Session):
        self.db = db
        self.source_repo = EvidenceSourceRepository(db)

    def _is_uniqueness_conflict(self, exc: IntegrityError) -> bool:
        """Determines if an IntegrityError was caused by a duplicate (user_id, source_uri)."""
        err_msg = str(exc.orig).lower() if exc.orig else str(exc).lower()
        if (
            "uq_evidence_sources_user_uri" in err_msg
            or "unique constraint failed: evidence_sources.user_id, evidence_sources.source_uri"
            in err_msg
        ):
            return True
        if "duplicate key" in err_msg and "evidence_sources" in err_msg:
            return True
        return False

    def register_source(
        self, user: User, source_in: EvidenceSourceCreate
    ) -> EvidenceSourceResponse:
        """
        Register a new evidence source for the authenticated candidate.

        Enforces:
        - URL normalization and host/scheme validation without network calls.
        - Initial status is strictly NOT_CHECKED; clients cannot claim verification.
        - last_checked_at is initialized to None.
        - Duplicate registration by the same candidate is rejected or safely re-activated.
        """
        try:
            normalized_uri = normalize_and_validate_url(
                source_in.source_uri, source_in.source_type
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        existing = self.source_repo.get_by_user_and_uri(user.id, normalized_uri)
        if existing:
            if existing.access_status != EvidenceSourceStatus.REVOKED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Evidence source with this URL is already registered for this candidate.",
                )
            # Re-activate previously revoked source
            update_data: dict[str, Any] = {
                "source_type": source_in.source_type,
                "access_mode": source_in.access_mode,
                "access_status": EvidenceSourceStatus.NOT_CHECKED,
                "last_checked_at": None,
            }
            updated = self.source_repo.update(existing, update_data)
            return EvidenceSourceResponse.model_validate(updated)

        db_source = EvidenceSource(
            user_id=user.id,
            source_type=source_in.source_type,
            source_uri=normalized_uri,
            access_mode=source_in.access_mode,
            access_status=EvidenceSourceStatus.NOT_CHECKED,
            last_checked_at=None,
        )

        try:
            created = self.source_repo.create(db_source)
        except IntegrityError as exc:
            self.db.rollback()
            if self._is_uniqueness_conflict(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Evidence source with this URL is already registered for this candidate.",
                ) from exc
            raise

        return EvidenceSourceResponse.model_validate(created)

    def list_sources(
        self,
        user: User,
        source_type: EvidenceSourceType | None = None,
        access_status: EvidenceSourceStatus | None = None,
    ) -> list[EvidenceSourceResponse]:
        """List all evidence sources owned by the authenticated candidate with optional filtering."""
        sources = self.source_repo.list_by_user(
            user.id, source_type=source_type, access_status=access_status
        )
        return [EvidenceSourceResponse.model_validate(s) for s in sources]

    def get_source(self, user: User, source_id: uuid.UUID) -> EvidenceSourceResponse:
        """Retrieve a specific evidence source by ID, enforcing candidate ownership."""
        source = self.source_repo.get_by_id(source_id)
        if not source or source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )
        return EvidenceSourceResponse.model_validate(source)

    def revoke_source(self, user: User, source_id: uuid.UUID) -> EvidenceSourceResponse:
        """
        Revoke authorization/access to an evidence source.
        Prevents future retrieval while preserving historical traceability.
        """
        source = self.source_repo.get_by_id(source_id)
        if not source or source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        updated = self.source_repo.update(
            source, {"access_status": EvidenceSourceStatus.REVOKED}
        )
        return EvidenceSourceResponse.model_validate(updated)

    def update_status(
        self,
        user: User,
        source_id: uuid.UUID,
        status_in: EvidenceSourceStatusUpdate,
    ) -> EvidenceSourceResponse:
        """
        Controlled lifecycle update.
        Candidates may only set status to REVOKED. All verification statuses are rejected.
        """
        if status_in.access_status != EvidenceSourceStatus.REVOKED:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Candidates may only revoke access to a source; verification statuses cannot be set directly.",
            )
        return self.revoke_source(user, source_id)
