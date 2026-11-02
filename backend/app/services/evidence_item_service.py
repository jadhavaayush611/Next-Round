import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import EvidenceSourceStatus
from app.models.user import User
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.schemas.evidence_item import (
    EvidenceItemCreate,
    EvidenceItemResponse,
)


class EvidenceItemService:
    """
    Internal domain service for persisting and querying observations gathered from evidence sources.
    Enforces source existence, source lifecycle validity, and candidate authorization boundaries.

    No candidate-facing write endpoints are exposed; observations are collected and written
    by internal services and trusted collectors.
    """

    def __init__(self, db: Session):
        self.db = db
        self.item_repo = EvidenceItemRepository(db)
        self.source_repo = EvidenceSourceRepository(db)

    def create_evidence_item(
        self,
        item_in: EvidenceItemCreate,
        user: User | None = None,
        allow_revoked: bool = False,
    ) -> EvidenceItemResponse:
        """
        Persist a new evidence item tied to a verified EvidenceSource.

        Invariants enforced:
        - The referenced EvidenceSource must exist in the database.
        - If a user/candidate is provided, the EvidenceSource must belong to that candidate.
        - By default, observations cannot be recorded against a REVOKED source.
        - Timestamps: retains caller-provided observation time (observed_at) while
          database server manages record creation time (created_at).
        """
        source = self.source_repo.get_by_id(item_in.evidence_source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced evidence source does not exist.",
            )

        if user is not None and source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced evidence source does not exist or is not owned by the specified candidate.",
            )

        if source.access_status == EvidenceSourceStatus.REVOKED and not allow_revoked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot record evidence items for a revoked evidence source.",
            )

        db_item = EvidenceItem(
            evidence_source_id=item_in.evidence_source_id,
            evidence_type=item_in.evidence_type,
            description=item_in.description,
            observed_data=item_in.observed_data,
            source_locator=item_in.source_locator,
            observed_at=item_in.observed_at,
        )

        created = self.item_repo.create(db_item)
        return EvidenceItemResponse.model_validate(created)

    def get_evidence_item(
        self, item_id: uuid.UUID, user: User | None = None
    ) -> EvidenceItemResponse:
        """
        Retrieve an evidence item by ID.
        If a user is provided, validates that the underlying evidence source belongs to them.
        """
        item = self.item_repo.get_by_id(item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence item not found.",
            )

        if user is not None and item.evidence_source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence item not found.",
            )

        return EvidenceItemResponse.model_validate(item)

    def list_items_for_source(
        self,
        source_id: uuid.UUID,
        user: User | None = None,
        evidence_type: EvidenceType | None = None,
    ) -> list[EvidenceItemResponse]:
        """
        List all observations recorded for an evidence source.
        Validates source existence and optional user ownership.
        Historical evidence items remain accessible even if the source was REVOKED.
        """
        source = self.source_repo.get_by_id(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        if user is not None and source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        items = self.item_repo.list_by_source(source_id, evidence_type=evidence_type)
        return [EvidenceItemResponse.model_validate(item) for item in items]

    def list_items_for_user(
        self,
        user: User,
        evidence_type: EvidenceType | None = None,
    ) -> list[EvidenceItemResponse]:
        """List all observations associated with any of the candidate's registered sources."""
        items = self.item_repo.list_by_user(user.id, evidence_type=evidence_type)
        return [EvidenceItemResponse.model_validate(item) for item in items]

    def count_items_for_source(
        self, source_id: uuid.UUID, user: User | None = None
    ) -> int:
        """Count total observations for an evidence source with authorization check."""
        source = self.source_repo.get_by_id(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        if user is not None and source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        return self.item_repo.count_by_source(source_id)
