import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.assessment_task import AssessmentTask


class AssessmentType(enum.StrEnum):
    """Categorization of assessment format and focus."""

    PRACTICAL_CODING = "PRACTICAL_CODING"
    SYSTEM_DESIGN = "SYSTEM_DESIGN"
    CONCEPTUAL_KNOWLEDGE = "CONCEPTUAL_KNOWLEDGE"
    DEBUGGING_REVIEW = "DEBUGGING_REVIEW"


class AssessmentDifficulty(enum.StrEnum):
    """Target seniority/complexity level of the assessment."""

    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class AssessmentStatus(enum.StrEnum):
    """Lifecycle states for assessment definitions."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class AssessmentDefinition(Base):
    """
    Persistent specification and catalog entry for an assessment.
    Represents an immutable, versioned evaluation definition against which
    future candidate assessment attempts can be executed without historical drift.

    Invariants:
    - Stable identifier + explicit version number combination is unique.
    - Published versions (and deprecated versions) are strictly immutable.
    - Any revisions create a new version record in DRAFT status.
    - Only PUBLISHED assessment versions are accessible to candidates.
    """

    __tablename__ = "assessment_definitions"
    __table_args__ = (
        UniqueConstraint(
            "identifier",
            "version",
            name="uq_assessment_definitions_identifier_version",
        ),
        CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_assessment_definitions_identifier_not_empty",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_definitions_version_positive",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assessment_definitions_title_not_empty",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_assessment_definitions_duration_positive",
        ),
        Index("ix_assessment_definitions_identifier", "identifier"),
        Index("ix_assessment_definitions_status", "status"),
        Index(
            "ix_assessment_definitions_status_type_diff",
            "status",
            "assessment_type",
            "difficulty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, name="assessment_type"),
        nullable=False,
    )
    difficulty: Mapped[AssessmentDifficulty] = mapped_column(
        Enum(AssessmentDifficulty, name="assessment_difficulty"),
        nullable=False,
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus, name="assessment_status"),
        nullable=False,
        default=AssessmentStatus.DRAFT,
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
    tasks: Mapped[list["AssessmentTask"]] = relationship(
        "AssessmentTask",
        back_populates="assessment_definition",
        cascade="all, delete-orphan",
        order_by="AssessmentTask.order_index",
    )
