import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.candidate_claim import CandidateClaim
from app.models.evidence_source import EvidenceSource
from app.models.verification_result import VerificationResult
from app.repositories.base import BaseRepository


class VerificationResultRepository(BaseRepository[VerificationResult]):
    """Repository for managing immutable verification results and evidence associations."""

    def __init__(self, db: Session):
        super().__init__(VerificationResult, db)

    def get_by_id(self, result_id: uuid.UUID) -> VerificationResult | None:
        """Fetch verification result by primary key with relationships eagerly loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.evidence_items),
                selectinload(self.model.candidate_claim),
                selectinload(self.model.evidence_source),
            )
            .where(self.model.id == result_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_claim(self, claim_id: uuid.UUID) -> Sequence[VerificationResult]:
        """List all verification results for a given candidate claim ordered chronologically."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.evidence_items),
                selectinload(self.model.candidate_claim),
                selectinload(self.model.evidence_source),
            )
            .where(self.model.candidate_claim_id == claim_id)
            .order_by(self.model.checked_at.desc(), self.model.created_at.desc())
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_source(self, source_id: uuid.UUID) -> Sequence[VerificationResult]:
        """List all verification results for a given evidence source ordered chronologically."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.evidence_items),
                selectinload(self.model.candidate_claim),
                selectinload(self.model.evidence_source),
            )
            .where(self.model.evidence_source_id == source_id)
            .order_by(self.model.checked_at.desc(), self.model.created_at.desc())
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_user(self, user_id: uuid.UUID) -> Sequence[VerificationResult]:
        """List all verification results for a candidate across claims and sources."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.evidence_items),
                selectinload(self.model.candidate_claim),
                selectinload(self.model.evidence_source),
            )
            .outerjoin(
                CandidateClaim,
                self.model.candidate_claim_id == CandidateClaim.id,
            )
            .outerjoin(
                EvidenceSource,
                self.model.evidence_source_id == EvidenceSource.id,
            )
            .where(
                or_(
                    CandidateClaim.user_id == user_id,
                    EvidenceSource.user_id == user_id,
                )
            )
            .order_by(self.model.checked_at.desc(), self.model.created_at.desc())
            .distinct()
        )
        return self.db.execute(stmt).scalars().all()

    def count_by_claim(self, claim_id: uuid.UUID) -> int:
        """Count total verification attempts performed for a candidate claim."""
        stmt = select(func.count(self.model.id)).where(
            self.model.candidate_claim_id == claim_id
        )
        result = self.db.execute(stmt).scalar_one_or_none()
        return result or 0

    def count_by_source(self, source_id: uuid.UUID) -> int:
        """Count total verification attempts performed for an evidence source."""
        stmt = select(func.count(self.model.id)).where(
            self.model.evidence_source_id == source_id
        )
        result = self.db.execute(stmt).scalar_one_or_none()
        return result or 0

    def update(
        self, db_obj: VerificationResult, update_data: dict[str, Any]
    ) -> VerificationResult:
        """VerificationResult records are immutable audit records and cannot be modified."""
        raise NotImplementedError(
            "VerificationResult records are immutable audit records and cannot be modified."
        )

    def remove(self, id: Any) -> VerificationResult | None:
        """VerificationResult records are immutable audit records and cannot be deleted."""
        raise NotImplementedError(
            "VerificationResult records are immutable audit records and cannot be deleted."
        )
