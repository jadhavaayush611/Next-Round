import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.repositories.base import BaseRepository


class CandidateClaimRepository(BaseRepository[CandidateClaim]):
    """Repository for managing candidate claims and provenance queries."""

    def __init__(self, db: Session):
        super().__init__(CandidateClaim, db)

    def get_by_id(self, claim_id: uuid.UUID) -> CandidateClaim | None:
        """Fetch candidate claim by ID."""
        return self.get(claim_id)

    def list_by_user(
        self,
        user_id: uuid.UUID,
        claim_type: ClaimType | None = None,
        origin: ClaimOrigin | None = None,
    ) -> Sequence[CandidateClaim]:
        """List all claims for a given user, with optional claim_type and origin filters."""
        query = select(self.model).where(self.model.user_id == user_id)
        if claim_type is not None:
            query = query.where(self.model.claim_type == claim_type)
        if origin is not None:
            query = query.where(self.model.origin == origin)
        query = query.order_by(self.model.created_at.desc())
        return self.db.execute(query).scalars().all()

    def list_by_parse(self, parse_id: uuid.UUID) -> Sequence[CandidateClaim]:
        """List all claims tied to a specific ResumeParse snapshot."""
        query = (
            select(self.model)
            .where(self.model.resume_parse_id == parse_id)
            .order_by(self.model.created_at.desc())
        )
        return self.db.execute(query).scalars().all()
