import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.assessment_task import AssessmentTask


class EvaluationMode(enum.StrEnum):
    """Execution mode used to evaluate candidate submissions for a task."""

    AUTOMATED = "AUTOMATED"
    RUBRIC_MANUAL = "RUBRIC_MANUAL"
    RUBRIC_SEMI_AUTOMATED = "RUBRIC_SEMI_AUTOMATED"


class EvaluationRubric(Base):
    """
    Authoring and evaluator configuration for a specific assessment task.
    Maintains structured evaluation criteria, expected benchmarks, and private test definitions.
    Strictly isolated from candidate-facing API payloads.

    Invariants:
    - Belongs to exactly one AssessmentTask.
    - Strictly immutable once its parent assessment definition is published.
    - Contains structured, qualitative evaluation criteria without arbitrary weights or percentages.
    - Hidden test suites, solution keys, and reviewer rubrics remain evaluator-private.
    """

    __tablename__ = "evaluation_rubrics"
    __table_args__ = (Index("uq_evaluation_rubrics_task_id", "task_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_tasks.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    evaluation_mode: Mapped[EvaluationMode] = mapped_column(
        Enum(EvaluationMode, name="evaluation_mode"),
        nullable=False,
    )
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        default=list,
        nullable=False,
    )
    rubric_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    task: Mapped["AssessmentTask"] = relationship(
        "AssessmentTask", back_populates="rubric"
    )
