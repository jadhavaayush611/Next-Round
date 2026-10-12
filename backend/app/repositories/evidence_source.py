import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence_source import (
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.repositories.base import BaseRepository


class EvidenceSourceRepository(BaseRepository[EvidenceSource]):
    """Repository for managing candidate evidence sources and lifecycle queries."""

    def __init__(self, db: Session):
        super().__init__(EvidenceSource, db)

    def get_by_id(self, source_id: uuid.UUID) -> EvidenceSource | None:
        """Fetch evidence source by primary key ID."""
        return self.get(source_id)

    def get_by_user_and_uri(
        self, user_id: uuid.UUID, source_uri: str
    ) -> EvidenceSource | None:
        """Find a specific source by user ID and normalized URI."""
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.source_uri == source_uri)
        )
        return self.db.execute(query).scalars().first()

    def list_by_user(
        self,
        user_id: uuid.UUID,
        source_type: EvidenceSourceType | None = None,
        access_status: EvidenceSourceStatus | None = None,
    ) -> Sequence[EvidenceSource]:
        """List all evidence sources for a candidate with optional filtering."""
        query = select(self.model).where(self.model.user_id == user_id)
        if source_type is not None:
            query = query.where(self.model.source_type == source_type)
        if access_status is not None:
            query = query.where(self.model.access_status == access_status)
        query = query.order_by(self.model.created_at.desc())
        return self.db.execute(query).scalars().all()
