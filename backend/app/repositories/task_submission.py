import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import cast, func, select, update
from sqlalchemy.orm import Session

from app.models.task_submission import TaskSubmission, TaskSubmissionStatus
from app.repositories.base import BaseRepository


class TaskSubmissionRepository(BaseRepository[TaskSubmission]):
    """
    Repository for managing TaskSubmission entities.
    Supports child-row locking (step 2 of universal lock order),
    atomic optimistic revision updates, and aggregate payload size calculation.
    Defers transaction commits to service layers.
    """

    def __init__(self, db: Session):
        super().__init__(TaskSubmission, db)

    def _apply_for_update(self, stmt: Any) -> Any:
        """Applies row-level FOR UPDATE locking on PostgreSQL."""
        bind = self.db.get_bind()
        if bind and bind.dialect.name == "postgresql":
            return stmt.with_for_update()
        return stmt

    def get_by_id(
        self, submission_id: uuid.UUID, for_update: bool = False
    ) -> TaskSubmission | None:
        """Fetch submission by primary key."""
        stmt = select(self.model).where(self.model.id == submission_id)
        if for_update:
            stmt = self._apply_for_update(stmt)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_submission(
        self,
        attempt_id: uuid.UUID,
        task_id: uuid.UUID,
        for_update: bool = False,
    ) -> TaskSubmission | None:
        """
        Fetch submission for an exact attempt and task.
        Child-row lock: must only be called after acquiring parent AssessmentAttempt lock.
        """
        stmt = select(self.model).where(
            self.model.attempt_id == attempt_id,
            self.model.task_id == task_id,
        )
        if for_update:
            stmt = self._apply_for_update(stmt)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_attempt_id(self, attempt_id: uuid.UUID) -> Sequence[TaskSubmission]:
        """Fetch all submissions belonging to an attempt."""
        stmt = (
            select(self.model)
            .where(self.model.attempt_id == attempt_id)
            .order_by(self.model.created_at.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def create_submission(self, submission: TaskSubmission) -> TaskSubmission:
        """Add and flush a single submission. Does NOT commit."""
        self.db.add(submission)
        self.db.flush()
        return submission

    def create_submissions_batch(
        self, submissions: list[TaskSubmission]
    ) -> list[TaskSubmission]:
        """Add and flush multiple submissions (e.g. eager seeding). Does NOT commit."""
        self.db.add_all(submissions)
        self.db.flush()
        return submissions

    def update_submission_with_revision(
        self,
        attempt_id: uuid.UUID,
        task_id: uuid.UUID,
        expected_revision: int,
        submission_payload: dict[str, Any],
        status: TaskSubmissionStatus,
        last_saved_at: datetime | None = None,
    ) -> TaskSubmission | None:
        """
        Atomically updates a task submission if and only if revision == expected_revision.
        Increments revision by 1.
        Returns the updated entity, or None if revision mismatched (stale write) or row missing.
        Does NOT commit; only flushes.
        """
        now = datetime.now(UTC)
        stmt = (
            update(self.model)
            .where(
                self.model.attempt_id == attempt_id,
                self.model.task_id == task_id,
                self.model.revision == expected_revision,
            )
            .values(
                submission_payload=submission_payload,
                status=status,
                revision=self.model.revision + 1,
                last_saved_at=last_saved_at or now,
                updated_at=now,
            )
        )
        result = self.db.execute(stmt)
        if getattr(result, "rowcount", 0) == 0:
            return None

        self.db.flush()
        return self.get_submission(attempt_id, task_id)

    def get_aggregate_payload_size(
        self, attempt_id: uuid.UUID, exclude_task_id: uuid.UUID | None = None
    ) -> int:
        """
        Computes the aggregate UTF-8 byte size of all task submissions for an attempt,
        optionally excluding a specific task (to calculate headroom for an incoming autosave).
        Uses SQL string length casting compatible across PostgreSQL and SQLite.
        """
        query = select(
            func.coalesce(
                func.sum(func.length(cast(self.model.submission_payload, sa.String))),
                0,
            )
        ).where(self.model.attempt_id == attempt_id)

        if exclude_task_id is not None:
            query = query.where(self.model.task_id != exclude_task_id)

        return int(self.db.execute(query).scalar_one() or 0)
