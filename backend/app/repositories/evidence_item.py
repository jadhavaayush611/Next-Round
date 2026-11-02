import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import EvidenceSource
from app.repositories.base import BaseRepository


class EvidenceItemRepository(BaseRepository[EvidenceItem]):
    """Repository for managing observations recorded against candidate evidence sources."""

    def __init__(self, db: Session):
        super().__init__(EvidenceItem, db)

    def get_by_id(self, item_id: uuid.UUID) -> EvidenceItem | None:
        """Fetch evidence item by primary key ID."""
        return self.get(item_id)

    def list_by_source(
        self,
        source_id: uuid.UUID,
        evidence_type: EvidenceType | None = None,
    ) -> Sequence[EvidenceItem]:
        """List all evidence items for a given source ordered chronologically."""
        query = select(self.model).where(self.model.evidence_source_id == source_id)
        if evidence_type is not None:
            query = query.where(self.model.evidence_type == evidence_type)
        query = query.order_by(
            self.model.observed_at.desc(), self.model.created_at.desc()
        )
        return self.db.execute(query).scalars().all()

    def list_by_user(
        self,
        user_id: uuid.UUID,
        evidence_type: EvidenceType | None = None,
    ) -> Sequence[EvidenceItem]:
        """List all evidence items for a candidate by joining the parent EvidenceSource."""
        query = (
            select(self.model)
            .join(EvidenceSource, self.model.evidence_source_id == EvidenceSource.id)
            .where(EvidenceSource.user_id == user_id)
        )
        if evidence_type is not None:
            query = query.where(self.model.evidence_type == evidence_type)
        query = query.order_by(
            self.model.observed_at.desc(), self.model.created_at.desc()
        )
        return self.db.execute(query).scalars().all()

    def count_by_source(self, source_id: uuid.UUID) -> int:
        """Count total observations recorded for an evidence source."""
        query = select(func.count(self.model.id)).where(
            self.model.evidence_source_id == source_id
        )
        result = self.db.execute(query).scalar_one_or_none()
        return result or 0

    def update(self, db_obj: EvidenceItem, update_data: dict[str, Any]) -> EvidenceItem:
        """EvidenceItem records are immutable observations and cannot be edited."""
        raise NotImplementedError(
            "EvidenceItem records are immutable audit observations and cannot be modified."
        )

    def remove(self, id: Any) -> EvidenceItem | None:
        """EvidenceItem records are immutable observations and cannot be deleted."""
        raise NotImplementedError(
            "EvidenceItem records are immutable audit observations and cannot be deleted."
        )
