import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.user import User


class EvidenceSourceType(enum.StrEnum):
    """Supported classifications for candidate-provided evidence sources."""

    GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
    GITHUB_PROFILE = "GITHUB_PROFILE"
    LINKEDIN_PROFILE = "LINKEDIN_PROFILE"
    PORTFOLIO = "PORTFOLIO"
    ASSESSMENT = "ASSESSMENT"
    OTHER = "OTHER"


class AccessMode(enum.StrEnum):
    """Authorization mode required to inspect the source."""

    PUBLIC = "PUBLIC"
    AUTHORIZED = "AUTHORIZED"
    INTERNAL = "INTERNAL"


class EvidenceSourceStatus(enum.StrEnum):
    """Verification and accessibility lifecycle status of the source."""

    AVAILABLE = "AVAILABLE"
    INACCESSIBLE = "INACCESSIBLE"
    REVOKED = "REVOKED"
    ERROR = "ERROR"
    NOT_CHECKED = "NOT_CHECKED"


class EvidenceSource(Base):
    """
    Persistent representation of an external account, repository, profile, or assessment
    submitted by or on behalf of a candidate. Preserves source origin, normalized URI,
    and verification lifecycle status without trusting URLs as identity proof.
    """

    __tablename__ = "evidence_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "source_uri", name="uq_evidence_sources_user_uri"),
        Index("ix_evidence_sources_user_created", "user_id", "created_at"),
        Index("ix_evidence_sources_user_type", "user_id", "source_type"),
        Index("ix_evidence_sources_user_status", "user_id", "access_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[EvidenceSourceType] = mapped_column(
        Enum(
            EvidenceSourceType,
            name="evidence_source_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    access_mode: Mapped[AccessMode] = mapped_column(
        Enum(
            AccessMode,
            name="access_mode",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=AccessMode.PUBLIC,
        nullable=False,
    )
    access_status: Mapped[EvidenceSourceStatus] = mapped_column(
        Enum(
            EvidenceSourceStatus,
            name="evidence_source_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=EvidenceSourceStatus.NOT_CHECKED,
        nullable=False,
        index=True,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="evidence_sources")
