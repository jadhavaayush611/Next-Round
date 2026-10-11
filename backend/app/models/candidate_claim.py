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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.resume_parse import ResumeParse
    from app.models.user import User


class ClaimType(enum.StrEnum):
    """Domain classification for a candidate assertion."""

    SKILL = "SKILL"
    PROJECT = "PROJECT"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"
    OTHER = "OTHER"


class ClaimOrigin(enum.StrEnum):
    """Source provenance origin for a candidate claim."""

    RESUME = "RESUME"
    USER_DECLARED = "USER_DECLARED"


class CandidateClaim(Base):
    """
    Represents a specific placement assertion made by or on behalf of a candidate.
    Preserves exact origin and immutable provenance to resume parses without mutating history.
    """

    __tablename__ = "candidate_claims"
    __table_args__ = (
        CheckConstraint(
            "((origin = 'RESUME' AND resume_parse_id IS NOT NULL AND canonical_path IS NOT NULL) OR "
            "(origin = 'USER_DECLARED' AND resume_parse_id IS NULL AND canonical_path IS NULL))",
            name="ck_candidate_claims_provenance",
        ),
        Index("ix_candidate_claims_user_created", "user_id", "created_at"),
        Index("ix_candidate_claims_resume_parse_id", "resume_parse_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_parse_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_parses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    claim_type: Mapped[ClaimType] = mapped_column(
        Enum(
            ClaimType,
            name="claim_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origin: Mapped[ClaimOrigin] = mapped_column(
        Enum(
            ClaimOrigin,
            name="claim_origin",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="candidate_claims")
    resume_parse: Mapped["ResumeParse | None"] = relationship(
        "ResumeParse", back_populates="claims"
    )
