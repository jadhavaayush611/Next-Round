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
    String,
    Text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.evidence_source import EvidenceSource


class EvidenceType(enum.StrEnum):
    """Supported classifications for specific observations obtained from evidence sources."""

    REPOSITORY_METADATA = "REPOSITORY_METADATA"
    CODE_ARTIFACT = "CODE_ARTIFACT"
    DOCUMENTATION = "DOCUMENTATION"
    CONTRIBUTION_ACTIVITY = "CONTRIBUTION_ACTIVITY"
    ASSESSMENT_RESULT = "ASSESSMENT_RESULT"
    OTHER = "OTHER"


class EvidenceItem(Base):
    """
    Persistent record of a specific observation obtained from an evidence source.
    Preserves traceable provenance to the originating EvidenceSource, exact observation
    time, and minimal structured facts needed for claim verification checks.

    Foreign key deletion behavior:
    `evidence_source_id` is configured with ON DELETE RESTRICT to guarantee that
    deleting an EvidenceSource cannot silently erase dependent observations.
    Access revocation updates source status to REVOKED without deleting historical observations.
    """

    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_evidence_items_description_not_empty",
        ),
        Index("ix_evidence_items_source_created", "evidence_source_id", "created_at"),
        Index("ix_evidence_items_source_observed", "evidence_source_id", "observed_at"),
        Index("ix_evidence_items_source_type", "evidence_source_id", "evidence_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    evidence_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(
            EvidenceType,
            name="evidence_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    observed_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=True,
    )
    source_locator: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    evidence_source: Mapped["EvidenceSource"] = relationship(
        "EvidenceSource", back_populates="evidence_items"
    )
