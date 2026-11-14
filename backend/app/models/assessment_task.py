import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.assessment_definition import AssessmentDefinition
    from app.models.competency import Competency
    from app.models.evaluation_rubric import EvaluationRubric


class TaskType(enum.StrEnum):
    """Execution modality or interaction format of an individual assessment task."""

    CODING = "CODING"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    FREE_RESPONSE = "FREE_RESPONSE"
    CODE_ANALYSIS = "CODE_ANALYSIS"


class AssessmentTask(Base):
    """
    Individual evaluation item belonging to a specific assessment definition version.
    Maintains candidate-visible prompts and test fixtures strictly decoupled from
    evaluator-only rubrics and private grading artifacts.

    Invariants:
    - Belongs to an exact assessment definition version.
    - Stable identifier is unique within its parent definition version.
    - Sequential order_index is non-negative and unique within its definition.
    - Contains only candidate-visible instructions and fixtures.
    - Private grading configurations belong exclusively to the linked EvaluationRubric.
    """

    __tablename__ = "assessment_tasks"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "assessment_definition_id",
            name="uq_assessment_tasks_id_def_id",
        ),
        UniqueConstraint(
            "assessment_definition_id",
            "identifier",
            name="uq_assessment_tasks_definition_identifier",
        ),
        UniqueConstraint(
            "assessment_definition_id",
            "order_index",
            name="uq_assessment_tasks_definition_order",
        ),
        CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_assessment_tasks_identifier_not_empty",
        ),
        CheckConstraint(
            "order_index >= 0",
            name="ck_assessment_tasks_order_index_non_negative",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assessment_tasks_title_not_empty",
        ),
        CheckConstraint(
            "length(trim(prompt)) > 0",
            name="ck_assessment_tasks_prompt_not_empty",
        ),
        Index(
            "ix_assessment_tasks_definition_id",
            "assessment_definition_id",
        ),
        Index("ix_assessment_tasks_competency_id", "competency_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assessment_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    competency_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competencies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )
    task_metadata: Mapped[dict[str, Any]] = mapped_column(
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
    assessment_definition: Mapped["AssessmentDefinition"] = relationship(
        "AssessmentDefinition", back_populates="tasks"
    )
    competency: Mapped["Competency | None"] = relationship("Competency")
    rubric: Mapped["EvaluationRubric | None"] = relationship(
        "EvaluationRubric",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
    )
