import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.assessment_task import AssessmentTask
from app.repositories.base import BaseRepository


class AssessmentTaskRepository(BaseRepository[AssessmentTask]):
    """Repository for querying and managing assessment tasks."""

    def __init__(self, db: Session):
        super().__init__(AssessmentTask, db)

    def get_by_id(self, task_id: uuid.UUID) -> AssessmentTask | None:
        """Fetch task by primary key with rubric and competency eager loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.rubric),
                selectinload(self.model.competency),
                selectinload(self.model.assessment_definition),
            )
            .where(self.model.id == task_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_definition(self, definition_id: uuid.UUID) -> Sequence[AssessmentTask]:
        """List tasks belonging to an assessment definition ordered by order_index."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.rubric),
                selectinload(self.model.competency),
            )
            .where(self.model.assessment_definition_id == definition_id)
            .order_by(self.model.order_index.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def get_by_definition_and_identifier(
        self, definition_id: uuid.UUID, identifier: str
    ) -> AssessmentTask | None:
        """Fetch task by definition ID and task identifier."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.rubric),
                selectinload(self.model.competency),
            )
            .where(
                self.model.assessment_definition_id == definition_id,
                self.model.identifier == identifier,
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()
