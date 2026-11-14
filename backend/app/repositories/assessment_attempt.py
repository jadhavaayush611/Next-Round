import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.assessment_attempt import AssessmentAttempt, AttemptStatus
from app.models.assessment_definition import AssessmentDefinition
from app.repositories.base import BaseRepository


class AssessmentAttemptRepository(BaseRepository[AssessmentAttempt]):
    """
    Repository for managing candidate AssessmentAttempt entities.
    Enforces candidate-scoped queries, parent-row locking, and strictly defers
    transaction commits to service layers.
    """

    def __init__(self, db: Session):
        super().__init__(AssessmentAttempt, db)

    def _apply_for_update(self, stmt: Any) -> Any:
        """
        Applies row-level FOR UPDATE locking when supported by dialect (PostgreSQL).
        SQLite runs tests in transaction-level serializable mode and ignores row-level FOR UPDATE.
        """
        bind = self.db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            return stmt.with_for_update()
        return stmt

    def get_by_id(
        self, attempt_id: uuid.UUID, for_update: bool = False
    ) -> AssessmentAttempt | None:
        """Fetch attempt by primary key with optional parent-row locking."""
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.submissions),
                selectinload(self.model.assessment_definition).selectinload(
                    AssessmentDefinition.tasks
                ),
            )
            .where(self.model.id == attempt_id)
        )
        if for_update:
            stmt = self._apply_for_update(stmt)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_candidate_attempt(
        self,
        attempt_id: uuid.UUID,
        user_id: uuid.UUID,
        for_update: bool = False,
    ) -> AssessmentAttempt | None:
        """
        Fetch attempt scoped strictly to the candidate (user_id).
        When for_update=True, acquires parent-row lock (first step of universal lock order).
        """
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.submissions),
                selectinload(self.model.assessment_definition).selectinload(
                    AssessmentDefinition.tasks
                ),
            )
            .where(
                self.model.id == attempt_id,
                self.model.user_id == user_id,
            )
        )
        if for_update:
            stmt = self._apply_for_update(stmt)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active_attempt(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID,
        for_update: bool = False,
    ) -> AssessmentAttempt | None:
        """
        Find any active attempt (INITIALIZED or IN_PROGRESS) for this candidate and definition version.
        """
        stmt = (
            select(self.model)
            .options(
                selectinload(self.model.submissions),
                selectinload(self.model.assessment_definition).selectinload(
                    AssessmentDefinition.tasks
                ),
            )
            .where(
                self.model.user_id == user_id,
                self.model.assessment_definition_id == assessment_definition_id,
                self.model.status.in_(
                    [AttemptStatus.INITIALIZED, AttemptStatus.IN_PROGRESS]
                ),
            )
        )
        if for_update:
            stmt = self._apply_for_update(stmt)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_candidate_attempts(
        self,
        user_id: uuid.UUID,
        assessment_definition_id: uuid.UUID | None = None,
        status: AttemptStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[AssessmentAttempt], int]:
        """
        List candidate attempts with optional definition and status filtering,
        returning items and total count.
        """
        base_stmt = select(self.model).where(self.model.user_id == user_id)
        count_stmt = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )

        if assessment_definition_id is not None:
            base_stmt = base_stmt.where(
                self.model.assessment_definition_id == assessment_definition_id
            )
            count_stmt = count_stmt.where(
                self.model.assessment_definition_id == assessment_definition_id
            )
        if status is not None:
            base_stmt = base_stmt.where(self.model.status == status)
            count_stmt = count_stmt.where(self.model.status == status)

        total = self.db.execute(count_stmt).scalar_one() or 0

        items_stmt = (
            base_stmt.options(
                selectinload(self.model.submissions),
                selectinload(self.model.assessment_definition).selectinload(
                    AssessmentDefinition.tasks
                ),
            )
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = self.db.execute(items_stmt).scalars().all()
        return items, total

    def get_max_attempt_number(
        self, user_id: uuid.UUID, assessment_definition_id: uuid.UUID
    ) -> int:
        """
        Calculates MAX(attempt_number) for this user and definition version.
        Returns 0 if no prior attempts exist.
        """
        stmt = select(func.coalesce(func.max(self.model.attempt_number), 0)).where(
            self.model.user_id == user_id,
            self.model.assessment_definition_id == assessment_definition_id,
        )
        return int(self.db.execute(stmt).scalar_one() or 0)

    def create_attempt(self, attempt: AssessmentAttempt) -> AssessmentAttempt:
        """
        Flushes a new AssessmentAttempt to session.
        Does NOT commit, allowing service transaction orchestration.
        """
        self.db.add(attempt)
        self.db.flush()
        return attempt

    def update_attempt_status(
        self,
        attempt: AssessmentAttempt,
        status: AttemptStatus,
        started_at: datetime | None = None,
        expires_at: datetime | None = None,
        submitted_at: datetime | None = None,
    ) -> AssessmentAttempt:
        """
        Updates attempt status and timestamp boundaries.
        Flushes changes without committing.
        """
        attempt.status = status
        if started_at is not None:
            attempt.started_at = started_at
        if expires_at is not None:
            attempt.expires_at = expires_at
        if submitted_at is not None:
            attempt.submitted_at = submitted_at
        self.db.flush()
        return attempt
