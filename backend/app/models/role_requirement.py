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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.candidate_target import CandidateTarget
    from app.models.skill import Skill


class RequirementType(enum.StrEnum):
    """Domain classification for a role requirement."""

    SKILL = "SKILL"
    QUALIFICATION = "QUALIFICATION"
    EXPERIENCE = "EXPERIENCE"
    OTHER = "OTHER"


class RequirementImportance(enum.StrEnum):
    """Priority or weighting of a role requirement."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    UNSPECIFIED = "UNSPECIFIED"


class RequirementSourceType(enum.StrEnum):
    """Source provenance of a role requirement."""

    JOB_DESCRIPTION = "JOB_DESCRIPTION"
    CURATED_ROLE = "CURATED_ROLE"


class RoleRequirement(Base):
    """
    Represents a specific skill or qualification required by a candidate target.
    Preserves exact original wording and provenance without automatic inference.

    Invariants:
    - Every requirement belongs to a specific target configuration (CandidateTarget).
    - skill_id is nullable because some requirements are not technical skills.
    - Preserves original wording exactly as supplied after basic validation.
    - Ambiguous mappings remain unmapped (skill_id=None).
    """

    __tablename__ = "role_requirements"
    __table_args__ = (
        CheckConstraint(
            "length(trim(requirement_text)) > 0",
            name="ck_role_requirements_text_not_empty",
        ),
        Index("ix_role_requirements_candidate_target_id", "candidate_target_id"),
        Index("ix_role_requirements_skill_id", "skill_id"),
        Index(
            "ix_role_requirements_target_created", "candidate_target_id", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"),
        nullable=True,
    )
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_type: Mapped[RequirementType] = mapped_column(
        Enum(
            RequirementType,
            name="requirement_type",
        ),
        nullable=False,
    )
    importance: Mapped[RequirementImportance] = mapped_column(
        Enum(
            RequirementImportance,
            name="requirement_importance",
        ),
        nullable=False,
    )
    source_type: Mapped[RequirementSourceType] = mapped_column(
        Enum(
            RequirementSourceType,
            name="requirement_source_type",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    candidate_target: Mapped["CandidateTarget"] = relationship(
        "CandidateTarget", back_populates="role_requirements"
    )
    skill: Mapped["Skill | None"] = relationship("Skill")
