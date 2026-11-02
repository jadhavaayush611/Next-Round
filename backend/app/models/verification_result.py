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
    from app.models.candidate_claim import CandidateClaim
    from app.models.evidence_item import EvidenceItem
    from app.models.evidence_source import EvidenceSource


class VerificationType(enum.StrEnum):
    """Domain classification for verification check methodology."""

    SOURCE_EXISTENCE = "SOURCE_EXISTENCE"
    CLAIM_SUPPORT = "CLAIM_SUPPORT"
    ASSESSMENT = "ASSESSMENT"
    OTHER = "OTHER"


class VerificationOutcome(enum.StrEnum):
    """Supported determination outcomes of a verification check."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationResult(Base):
    """
    Persistent record of a defined verification check outcome and reasoning.
    Preserves historical immutability, exact method version, timestamp, and
    traceable links to candidate claims, evidence sources, and supporting evidence items.

    Foreign key deletion behavior:
    `candidate_claim_id` and `evidence_source_id` are configured with ON DELETE RESTRICT
    to prevent deletion of parent claims or sources from silently erasing audit records.
    Historical verification results cannot be updated or deleted.
    """

    __tablename__ = "verification_results"
    __table_args__ = (
        CheckConstraint(
            "(candidate_claim_id IS NOT NULL OR evidence_source_id IS NOT NULL)",
            name="ck_verification_results_target_present",
        ),
        CheckConstraint(
            "(verification_type != 'CLAIM_SUPPORT' OR candidate_claim_id IS NOT NULL)",
            name="ck_verification_results_claim_support_requires_claim",
        ),
        CheckConstraint(
            "length(trim(method_version)) > 0",
            name="ck_verification_results_method_version_not_empty",
        ),
        CheckConstraint(
            "length(trim(explanation)) > 0",
            name="ck_verification_results_explanation_not_empty",
        ),
        Index(
            "ix_verification_results_claim_created",
            "candidate_claim_id",
            "created_at",
        ),
        Index(
            "ix_verification_results_source_created",
            "evidence_source_id",
            "created_at",
        ),
        Index("ix_verification_results_checked_at", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_claims.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    verification_type: Mapped[VerificationType] = mapped_column(
        Enum(
            VerificationType,
            name="verification_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    outcome: Mapped[VerificationOutcome] = mapped_column(
        Enum(
            VerificationOutcome,
            name="verification_outcome",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    method_version: Mapped[str] = mapped_column(String(100), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    candidate_claim: Mapped["CandidateClaim | None"] = relationship(
        "CandidateClaim", back_populates="verification_results"
    )
    evidence_source: Mapped["EvidenceSource | None"] = relationship(
        "EvidenceSource", back_populates="verification_results"
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        "EvidenceItem",
        secondary="verification_evidence",
        back_populates="verification_results",
        passive_deletes="all",
    )


class VerificationEvidence(Base):
    """
    Many-to-many join model linking a VerificationResult to the specific EvidenceItem
    observations that supported, contradicted, or informed the verification outcome.

    Foreign key deletion behavior:
    Both `verification_result_id` and `evidence_item_id` are configured with ON DELETE RESTRICT
    to prevent deletion of linked verification results or evidence observations from silently
    erasing audit history.
    """

    __tablename__ = "verification_evidence"
    __table_args__ = (
        Index("ix_verification_evidence_evidence_item_id", "evidence_item_id"),
    )

    verification_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_results.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    )
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    )

    # Direct relationships
    verification_result: Mapped["VerificationResult"] = relationship(
        "VerificationResult",
        foreign_keys=[verification_result_id],
        overlaps="evidence_items,verification_results",
    )
    evidence_item: Mapped["EvidenceItem"] = relationship(
        "EvidenceItem",
        foreign_keys=[evidence_item_id],
        overlaps="evidence_items,verification_results",
    )
