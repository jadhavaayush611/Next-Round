import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.candidate_target import CandidateTarget
    from app.models.user import User


class CandidateProfile(Base):
    """
    Candidate-owned placement goals and preferences that cannot reliably be derived from a resume.
    Enforces a strict 1:1 relationship with User.
    """

    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint(
            "graduation_year IS NULL OR (graduation_year >= 1950 AND graduation_year <= 2100)",
            name="ck_candidate_profiles_graduation_year",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    preferred_locations: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=True,
    )
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    user: Mapped["User"] = relationship("User", back_populates="candidate_profile")
    targets: Mapped[list["CandidateTarget"]] = relationship(
        "CandidateTarget",
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        order_by="CandidateTarget.created_at.desc()",
    )
