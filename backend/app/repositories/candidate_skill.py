import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.repositories.base import BaseRepository


class CandidateSkillRepository(BaseRepository[CandidateSkill]):
    """Repository for querying, indexing, and persisting candidate skill associations and evidence links."""

    def __init__(self, db: Session):
        super().__init__(CandidateSkill, db)

    def get_by_id(self, candidate_skill_id: uuid.UUID) -> CandidateSkill | None:
        """Fetch candidate skill by primary key with skill and evidence links eagerly loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.skill),
                selectinload(self.model.evidence_links),
            )
            .where(self.model.id == candidate_skill_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_user_and_skill(
        self, user_id: uuid.UUID, skill_id: uuid.UUID
    ) -> CandidateSkill | None:
        """Fetch candidate skill by candidate user ID and canonical skill ID."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.skill),
                selectinload(self.model.evidence_links),
            )
            .where(
                self.model.user_id == user_id,
                self.model.skill_id == skill_id,
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_user(
        self, user_id: uuid.UUID, skill_id: uuid.UUID | None = None
    ) -> Sequence[CandidateSkill]:
        """List all skill associations for a user, ordered by created_at desc."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.skill),
                selectinload(self.model.evidence_links),
            )
            .where(self.model.user_id == user_id)
        )
        if skill_id is not None:
            stmt = stmt.where(self.model.skill_id == skill_id)
        stmt = stmt.order_by(self.model.created_at.desc())
        return self.db.execute(stmt).scalars().all()

    def add_evidence_link(
        self, evidence_link: CandidateSkillEvidence
    ) -> CandidateSkillEvidence:
        """Persist a new CandidateSkillEvidence join record."""
        self.db.add(evidence_link)
        self.db.commit()
        self.db.refresh(evidence_link)
        return evidence_link

    def get_evidence_link(
        self,
        candidate_skill_id: uuid.UUID,
        claim_id: uuid.UUID | None = None,
        item_id: uuid.UUID | None = None,
    ) -> CandidateSkillEvidence | None:
        """Fetch an existing evidence link for a candidate skill by claim or evidence item."""
        stmt = select(CandidateSkillEvidence).where(
            CandidateSkillEvidence.candidate_skill_id == candidate_skill_id
        )
        if claim_id is not None:
            stmt = stmt.where(CandidateSkillEvidence.candidate_claim_id == claim_id)
        if item_id is not None:
            stmt = stmt.where(CandidateSkillEvidence.evidence_item_id == item_id)
        return self.db.execute(stmt).scalars().first()
