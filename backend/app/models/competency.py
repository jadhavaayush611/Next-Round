import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.skill import Skill


class CompetencyDimension(enum.StrEnum):
    """Core evaluation dimensions for technical competencies."""

    KNOWLEDGE = "KNOWLEDGE"
    PRACTICAL_IMPLEMENTATION = "PRACTICAL_IMPLEMENTATION"
    DEBUGGING_CODE_COMPREHENSION = "DEBUGGING_CODE_COMPREHENSION"
    SYSTEM_DESIGN_TRADEOFFS = "SYSTEM_DESIGN_TRADEOFFS"
    TECHNICAL_COMMUNICATION = "TECHNICAL_COMMUNICATION"


class Competency(Base):
    """
    Represents a specific, evaluatable capability dimension grounded in a canonical Skill.
    Preserves distinction between general technology identity (Skill) and observable
    engineering competencies across standardized dimensions.

    Invariants:
    - Must reference a valid canonical Skill in the shared catalog.
    - Has a stable, unique identifier (e.g. 'py-debugging-race-conditions').
    - Does not duplicate canonical skill names or aliases.
    - Dimension must be one of the standardized CompetencyDimension values.
    - Inactive competencies are retained for historical auditability.
    """

    __tablename__ = "competencies"
    __table_args__ = (
        CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_competencies_identifier_not_empty",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_competencies_name_not_empty",
        ),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_competencies_description_not_empty",
        ),
        Index(
            "uq_competencies_identifier_lower",
            text("lower(trim(identifier))"),
            unique=True,
        ),
        Index("ix_competencies_skill_id", "skill_id"),
        Index("ix_competencies_dimension", "dimension"),
        Index("ix_competencies_skill_dimension", "skill_id", "dimension"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"),
        nullable=False,
    )
    identifier: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[CompetencyDimension] = mapped_column(
        Enum(
            CompetencyDimension,
            name="competency_dimension",
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    skill: Mapped["Skill"] = relationship("Skill")
