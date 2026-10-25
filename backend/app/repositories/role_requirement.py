import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
    RoleRequirement,
)
from app.repositories.base import BaseRepository


class RoleRequirementRepository(BaseRepository[RoleRequirement]):
    """Repository for querying, indexing, and persisting candidate target role requirements."""

    def __init__(self, db: Session):
        super().__init__(RoleRequirement, db)

    def get_by_id(self, requirement_id: uuid.UUID) -> RoleRequirement | None:
        """Fetch role requirement by primary key with relationships loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.candidate_target),
                selectinload(self.model.skill),
            )
            .where(self.model.id == requirement_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_target(
        self,
        candidate_target_id: uuid.UUID,
        requirement_type: RequirementType | None = None,
        importance: RequirementImportance | None = None,
        source_type: RequirementSourceType | None = None,
    ) -> Sequence[RoleRequirement]:
        """List all role requirements for a specific target, ordered by created_at asc."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.candidate_target),
                selectinload(self.model.skill),
            )
            .where(self.model.candidate_target_id == candidate_target_id)
        )
        if requirement_type is not None:
            stmt = stmt.where(self.model.requirement_type == requirement_type)
        if importance is not None:
            stmt = stmt.where(self.model.importance == importance)
        if source_type is not None:
            stmt = stmt.where(self.model.source_type == source_type)
        stmt = stmt.order_by(self.model.created_at.asc())
        return self.db.execute(stmt).scalars().all()
