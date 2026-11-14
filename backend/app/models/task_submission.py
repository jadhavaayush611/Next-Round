import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.assessment_attempt import AssessmentAttempt
    from app.models.assessment_task import AssessmentTask


class TaskSubmissionStatus(enum.StrEnum):
    """Completion status of an individual task submission within an attempt."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class TaskSubmission(Base):
    """
    Candidate submission record for a single task within an assessment attempt.
    Enforces composite foreign key version integrity ensuring the task and attempt
    belong to the exact same assessment definition version.
    """

    __tablename__ = "task_submissions"
    __table_args__ = (
        # 1. Exactly one submission record per task per attempt
        UniqueConstraint(
            "attempt_id",
            "task_id",
            name="uq_task_submissions_attempt_task",
        ),
        # 2. Composite FK 1: verifies attempt exists and matches assessment_definition_id
        ForeignKeyConstraint(
            ["attempt_id", "assessment_definition_id"],
            [
                "assessment_attempts.id",
                "assessment_attempts.assessment_definition_id",
            ],
            name="fk_task_submissions_attempt_def",
            ondelete="CASCADE",
        ),
        # 3. Composite FK 2: verifies task exists and matches the EXACT SAME assessment_definition_id
        ForeignKeyConstraint(
            ["task_id", "assessment_definition_id"],
            [
                "assessment_tasks.id",
                "assessment_tasks.assessment_definition_id",
            ],
            name="fk_task_submissions_task_def",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_task_submissions_revision_positive",
        ),
        Index("ix_task_submissions_attempt_id", "attempt_id"),
        Index("ix_task_submissions_task_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    assessment_definition_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[TaskSubmissionStatus] = mapped_column(
        Enum(TaskSubmissionStatus, name="task_submission_status"),
        nullable=False,
        default=TaskSubmissionStatus.NOT_STARTED,
    )
    submission_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    last_saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    attempt: Mapped["AssessmentAttempt"] = relationship(
        "AssessmentAttempt",
        back_populates="submissions",
    )
    task: Mapped["AssessmentTask"] = relationship(
        "AssessmentTask",
        overlaps="attempt,submissions",
    )
