import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.resume import Resume


class ParseStatus(enum.StrEnum):
    """Lifecycle status for a resume semantic parse snapshot."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class ResumeParse(Base):
    """
    Persistent representation of a semantic parse snapshot for a specific resume version.
    Stores immutable canonical data as JSONB and tracks parsing lifecycle independently of Resume.status.
    """

    __tablename__ = "resume_parses"
    __table_args__ = (
        Index("ix_resume_parses_resume_id_status", "resume_id", "status"),
        Index("ix_resume_parses_resume_created", "resume_id", "created_at"),
        Index(
            "ix_resume_parses_version_lookup",
            "resume_id",
            "resume_version",
            "parser_version",
            "schema_version",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ParseStatus] = mapped_column(
        Enum(
            ParseStatus,
            name="parse_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ParseStatus.PROCESSING,
        nullable=False,
        index=True,
    )
    canonical_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=True,
    )
    extraction_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
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
    resume: Mapped["Resume"] = relationship("Resume", back_populates="parses")
