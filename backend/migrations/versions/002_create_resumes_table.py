"""Create resumes table with storage metadata and versioning

Revision ID: 002_create_resumes_table
Revises: 001_add_user_profile_fields
Create Date: 2026-07-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_create_resumes_table"
down_revision: str | None = "001_add_user_profile_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    resume_status = sa.Enum(
        "UPLOADED",
        "PROCESSING",
        "READY",
        "FAILED",
        "ARCHIVED",
        name="resume_status",
    )

    op.create_table(
        "resumes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", resume_status, nullable=False, server_default="UPLOADED"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("file_size > 0", name="ck_resumes_file_size_positive"),
        sa.CheckConstraint("version > 0", name="ck_resumes_version_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_resumes_storage_key"),
        sa.UniqueConstraint("user_id", "version", name="uq_resumes_user_version"),
    )
    op.create_index(op.f("ix_resumes_user_id"), "resumes", ["user_id"], unique=False)
    op.create_index(op.f("ix_resumes_storage_key"), "resumes", ["storage_key"], unique=True)
    op.create_index(
        "ix_resumes_user_id_version", "resumes", ["user_id", "version"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_resumes_user_id_version", table_name="resumes")
    op.drop_index(op.f("ix_resumes_storage_key"), table_name="resumes")
    op.drop_index(op.f("ix_resumes_user_id"), table_name="resumes")
    op.drop_table("resumes")

    resume_status = sa.Enum(
        "UPLOADED",
        "PROCESSING",
        "READY",
        "FAILED",
        "ARCHIVED",
        name="resume_status",
    )
    resume_status.drop(op.get_bind(), checkfirst=True)
