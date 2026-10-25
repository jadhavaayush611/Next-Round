import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.candidate_profile import CandidateProfile
    from app.models.role_requirement import RoleRequirement


class CandidateTarget(Base):
    """
    Represents one specific target role, company, and job description configuration.
    Preserves historical targets, enforcing that at most one target per profile is active.
    """

    __tablename__ = "candidate_targets"
    __table_args__ = (
        Index(
            "uq_candidate_targets_active_profile",
            "candidate_profile_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
        Index(
            "ix_candidate_targets_profile_created", "candidate_profile_id", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    candidate_profile: Mapped["CandidateProfile"] = relationship(
        "CandidateProfile", back_populates="targets"
    )
    role_requirements: Mapped[list["RoleRequirement"]] = relationship(
        "RoleRequirement",
        back_populates="candidate_target",
        order_by="RoleRequirement.created_at.asc()",
    )
