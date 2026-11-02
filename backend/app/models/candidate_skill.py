import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.candidate_claim import CandidateClaim
    from app.models.evidence_item import EvidenceItem
    from app.models.skill import Skill
    from app.models.user import User


class CandidateSkill(Base):
    """
    Associates a candidate with a canonical Skill referenced by claims or supported by evidence.
    Enforces server-managed timestamps and unique user-to-canonical-skill associations.

    Invariants:
    - Unique (user_id, skill_id) prevents duplicate skill associations for the same candidate.
    - Before a CandidateSkill is presented as evidence-backed, it must have at least one supporting
      claim, evidence item, or assessment result.
    - Claim-only associations remain claims, not demonstrated proficiency.
    - No proficiency or confidence scores are stored.
    """

    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_candidate_skills_user_skill"),
        Index("ix_candidate_skills_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    user: Mapped["User"] = relationship("User", back_populates="candidate_skills")
    skill: Mapped["Skill"] = relationship("Skill")
    evidence_links: Mapped[list["CandidateSkillEvidence"]] = relationship(
        "CandidateSkillEvidence",
        back_populates="candidate_skill",
        cascade="all, delete-orphan",
    )


class CandidateSkillEvidence(Base):
    """
    Join model linking a CandidateSkill association to its supporting CandidateClaim or EvidenceItem.
    Enforces the invariant that exactly one provenance source (claim or evidence item) is populated.

    Invariants:
    - Exactly one of candidate_claim_id and evidence_item_id must be populated for each join row.
    - Cannot link the same claim or evidence item multiple times to the same candidate skill.
    """

    __tablename__ = "candidate_skill_evidence"
    __table_args__ = (
        CheckConstraint(
            "((candidate_claim_id IS NOT NULL AND evidence_item_id IS NULL) OR "
            "(candidate_claim_id IS NULL AND evidence_item_id IS NOT NULL))",
            name="ck_candidate_skill_evidence_exactly_one_source",
        ),
        Index(
            "uq_candidate_skill_evidence_skill_claim",
            "candidate_skill_id",
            "candidate_claim_id",
            unique=True,
            postgresql_where=text("candidate_claim_id IS NOT NULL"),
            sqlite_where=text("candidate_claim_id IS NOT NULL"),
        ),
        Index(
            "uq_candidate_skill_evidence_skill_item",
            "candidate_skill_id",
            "evidence_item_id",
            unique=True,
            postgresql_where=text("evidence_item_id IS NOT NULL"),
            sqlite_where=text("evidence_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_claims.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    candidate_skill: Mapped["CandidateSkill"] = relationship(
        "CandidateSkill", back_populates="evidence_links"
    )
    candidate_claim: Mapped["CandidateClaim | None"] = relationship("CandidateClaim")
    evidence_item: Mapped["EvidenceItem | None"] = relationship("EvidenceItem")
