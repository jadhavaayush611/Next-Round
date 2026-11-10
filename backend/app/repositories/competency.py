import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.competency import Competency, CompetencyDimension
from app.repositories.base import BaseRepository


class CompetencyRepository(BaseRepository[Competency]):
    """Repository for querying and persisting Competency entities."""

    def __init__(self, db: Session):
        super().__init__(Competency, db)

    def get_by_id(self, competency_id: uuid.UUID) -> Competency | None:
        """Fetch competency by primary key UUID with Skill eager loaded."""
        stmt = (
            select(self.model)
            .options(selectinload(self.model.skill))
            .where(self.model.id == competency_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_identifier(self, identifier: str) -> Competency | None:
        """Fetch competency by stable unique identifier (case-insensitive)."""
        stripped = identifier.strip().lower()
        if not stripped:
            return None
        stmt = (
            select(self.model)
            .options(selectinload(self.model.skill))
            .where(func.lower(self.model.identifier) == stripped)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(
        self,
        skill_id: uuid.UUID | None = None,
        dimension: CompetencyDimension | None = None,
        is_active: bool | None = None,
    ) -> Sequence[Competency]:
        """List competencies with optional skill, dimension, and active state filters."""
        stmt = (
            select(self.model)
            .options(selectinload(self.model.skill))
            .order_by(self.model.identifier.asc())
        )
        if skill_id is not None:
            stmt = stmt.where(self.model.skill_id == skill_id)
        if dimension is not None:
            stmt = stmt.where(self.model.dimension == dimension)
        if is_active is not None:
            stmt = stmt.where(self.model.is_active == is_active)
        return self.db.execute(stmt).scalars().all()

    def count(self) -> int:
        """Count total competencies."""
        stmt = select(func.count(self.model.id))
        result = self.db.execute(stmt).scalar_one_or_none()
        return result or 0

    def get_published_assessment_references(
        self, competency_id: uuid.UUID
    ) -> list[str]:
        """Return list of distinct published assessment identifiers that reference this competency."""
        from app.models.assessment_definition import (
            AssessmentDefinition,
            AssessmentStatus,
        )
        from app.models.assessment_task import AssessmentTask

        stmt = (
            select(AssessmentDefinition.identifier)
            .join(
                AssessmentTask,
                AssessmentTask.assessment_definition_id == AssessmentDefinition.id,
            )
            .where(
                AssessmentTask.competency_id == competency_id,
                AssessmentDefinition.status == AssessmentStatus.PUBLISHED,
            )
            .distinct()
        )
        return list(self.db.execute(stmt).scalars().all())
