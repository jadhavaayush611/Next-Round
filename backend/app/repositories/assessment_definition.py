import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask
from app.models.competency import Competency
from app.repositories.base import BaseRepository


class AssessmentDefinitionRepository(BaseRepository[AssessmentDefinition]):
    """Repository for querying, versioning, and persisting AssessmentDefinition entities."""

    def __init__(self, db: Session):
        super().__init__(AssessmentDefinition, db)

    def get_by_id(self, definition_id: uuid.UUID) -> AssessmentDefinition | None:
        """Fetch definition by UUID with tasks, competencies, and rubrics loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.tasks)
                .selectinload(AssessmentTask.competency)
                .selectinload(Competency.skill),
                selectinload(self.model.tasks).selectinload(AssessmentTask.rubric),
            )
            .where(self.model.id == definition_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_identifier_and_version(
        self, identifier: str, version: int
    ) -> AssessmentDefinition | None:
        """Fetch an exact version record for a given assessment identifier."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.tasks)
                .selectinload(AssessmentTask.competency)
                .selectinload(Competency.skill),
                selectinload(self.model.tasks).selectinload(AssessmentTask.rubric),
            )
            .where(
                self.model.identifier == identifier,
                self.model.version == version,
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_published(self, identifier: str) -> AssessmentDefinition | None:
        """Fetch the latest published version of a specific assessment identifier."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.tasks)
                .selectinload(AssessmentTask.competency)
                .selectinload(Competency.skill),
                selectinload(self.model.tasks).selectinload(AssessmentTask.rubric),
            )
            .where(
                self.model.identifier == identifier,
                self.model.status == AssessmentStatus.PUBLISHED,
            )
            .order_by(self.model.version.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def get_max_version(self, identifier: str) -> int:
        """Query the current maximum version number for an assessment identifier."""
        stmt = select(func.max(self.model.version)).where(
            self.model.identifier == identifier
        )
        res = self.db.execute(stmt).scalar()
        return res if res is not None else 0

    def list_latest_published(
        self,
        assessment_type: AssessmentType | None = None,
        difficulty: AssessmentDifficulty | None = None,
        skill_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[AssessmentDefinition], int]:
        """
        List distinct assessments resolving strictly to each identifier's latest published version.
        Guarantees that multiple historical versions of the same assessment are never duplicated.
        Returns (items, total_count).
        """
        # 1. Subquery to find max published version per identifier
        subq = (
            select(
                self.model.identifier.label("sub_identifier"),
                func.max(self.model.version).label("max_version"),
            )
            .where(self.model.status == AssessmentStatus.PUBLISHED)
            .group_by(self.model.identifier)
            .subquery()
        )

        # 2. Main query joining to latest published version
        stmt = (
            select(self.model)
            .join(
                subq,
                (self.model.identifier == subq.c.sub_identifier)
                & (self.model.version == subq.c.max_version),
            )
            .where(self.model.status == AssessmentStatus.PUBLISHED)
        )

        # 3. Apply filters
        if assessment_type is not None:
            stmt = stmt.where(self.model.assessment_type == assessment_type)
        if difficulty is not None:
            stmt = stmt.where(self.model.difficulty == difficulty)
        if skill_id is not None:
            stmt = stmt.where(
                self.model.tasks.any(
                    AssessmentTask.competency.has(Competency.skill_id == skill_id)
                )
            )
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    self.model.title.ilike(pattern),
                    self.model.description.ilike(pattern),
                )
            )

        # 4. Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar() or 0

        # 5. Apply ordering, pagination and eager loading
        stmt = (
            stmt.options(
                selectinload(self.model.tasks)
                .selectinload(AssessmentTask.competency)
                .selectinload(Competency.skill),
            )
            .order_by(self.model.title.asc(), self.model.identifier.asc())
            .offset(offset)
            .limit(limit)
        )

        items = self.db.execute(stmt).scalars().all()
        return items, total
