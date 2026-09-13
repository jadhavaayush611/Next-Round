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
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.resume_parse import ResumeParse
    from app.models.user import User


class ResumeStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        CheckConstraint("file_size > 0", name="ck_resumes_file_size_positive"),
        CheckConstraint("version > 0", name="ck_resumes_version_positive"),
        UniqueConstraint("user_id", "version", name="uq_resumes_user_version"),
        Index("ix_resumes_user_id_version", "user_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False, index=True
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[ResumeStatus] = mapped_column(
        Enum(
            ResumeStatus,
            name="resume_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ResumeStatus.UPLOADED,
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

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resumes")
    parses: Mapped[list["ResumeParse"]] = relationship(
        "ResumeParse",
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeParse.created_at.desc()",
    )
