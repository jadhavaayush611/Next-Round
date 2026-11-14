import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.assessment_definition import AssessmentDefinition
    from app.models.task_submission import TaskSubmission
    from app.models.user import User


class AttemptStatus(enum.StrEnum):
    """Lifecycle states of a candidate assessment attempt."""

    INITIALIZED = "INITIALIZED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    EVALUATING = "EVALUATING"
    EVALUATED = "EVALUATED"
    MANUAL_REVIEW_PENDING = "MANUAL_REVIEW_PENDING"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"


class AssessmentAttempt(Base):
    """
    Candidate assessment attempt session tied to an exact, immutable AssessmentDefinition version.
    Maintains full historical integrity, timing boundaries, and strict state transitions.
    """

    __tablename__ = "assessment_attempts"
    __table_args__ = (
        # 1. Composite unique target constraint referenced by task_submissions composite FK
        UniqueConstraint(
            "id",
            "assessment_definition_id",
            name="uq_assessment_attempts_id_def_id",
        ),
        # 2. Sequential attempt numbering per candidate per exact assessment definition
        UniqueConstraint(
            "user_id",
            "assessment_definition_id",
            "attempt_number",
            name="uq_attempts_user_def_attempt_no",
        ),
        # 3. Timestamp sanity constraints
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_attempts_attempt_number_positive",
        ),
        CheckConstraint(
            "submitted_at IS NULL OR started_at IS NULL OR submitted_at >= started_at",
            name="ck_attempts_submitted_after_started",
        ),
        CheckConstraint(
            "expires_at IS NULL OR started_at IS NULL OR expires_at >= started_at",
            name="ck_attempts_expires_after_started",
        ),
        Index("ix_assessment_attempts_user_id", "user_id"),
        Index("ix_assessment_attempts_def_id", "assessment_definition_id"),
        Index("ix_assessment_attempts_status", "status"),
        # 4. Partial unique index: at most one active attempt per candidate per assessment version
        Index(
            "uq_one_active_attempt_per_user_def",
            "user_id",
            "assessment_definition_id",
            unique=True,
            postgresql_where=text("status IN ('INITIALIZED', 'IN_PROGRESS')"),
            sqlite_where=text("status IN ('INITIALIZED', 'IN_PROGRESS')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assessment_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[AttemptStatus] = mapped_column(
        Enum(AttemptStatus, name="attempt_status"),
        nullable=False,
        default=AttemptStatus.INITIALIZED,
    )
    # attempt_number has no default; must be explicitly calculated and assigned by service
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    user: Mapped["User"] = relationship("User", back_populates="assessment_attempts")
    assessment_definition: Mapped["AssessmentDefinition"] = relationship(
        "AssessmentDefinition", back_populates="attempts"
    )
    submissions: Mapped[list["TaskSubmission"]] = relationship(
        "TaskSubmission",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="TaskSubmission.created_at",
    )
