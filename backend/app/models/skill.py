import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.session import Base


class Skill(Base):
    """
    Persistent canonical skill in the shared NextRound technical catalog.
    Represents an unambiguous, normalized skill entity against which candidate claims,
    evidence items, assessments, and target-role requirements can be evaluated.

    Invariants:
    - Each canonical skill has one stable canonical name with case-insensitive uniqueness.
    - Category represents the high-level domain (e.g. Programming Language, Database, Framework).
    - Aliases store deterministic alternate names and abbreviations as a JSON list of strings.
    - Preserves distinction between distinct technologies (e.g. FastAPI vs Python).
    """

    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint(
            "length(trim(canonical_name)) > 0",
            name="ck_skills_canonical_name_not_empty",
        ),
        CheckConstraint(
            "length(trim(category)) > 0",
            name="ck_skills_category_not_empty",
        ),
        Index(
            "uq_skills_canonical_name_lower",
            text("lower(trim(canonical_name))"),
            unique=True,
        ),
        Index("ix_skills_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"),
        default=list,
        nullable=False,
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
