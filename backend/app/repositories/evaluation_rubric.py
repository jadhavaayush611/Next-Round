import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.evaluation_rubric import EvaluationRubric
from app.repositories.base import BaseRepository


class EvaluationRubricRepository(BaseRepository[EvaluationRubric]):
    """Repository for querying and managing task evaluation rubrics."""

    def __init__(self, db: Session):
        super().__init__(EvaluationRubric, db)

    def get_by_id(self, rubric_id: uuid.UUID) -> EvaluationRubric | None:
        """Fetch rubric by ID with task loaded."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.task),
            )
            .where(self.model.id == rubric_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_task_id(self, task_id: uuid.UUID) -> EvaluationRubric | None:
        """Fetch rubric by associated task ID."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.task),
            )
            .where(self.model.task_id == task_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()
