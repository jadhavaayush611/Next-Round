"""Create resume_parses table for canonical JSONB snapshots and versioning

Revision ID: 003_create_resume_parses_table
Revises: 002_create_resumes_table
Create Date: 2026-09-13 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_create_resume_parses_table"
down_revision: str | None = "002_create_resumes_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    parse_status = sa.Enum(
        "PROCESSING",
        "READY",
        "FAILED",
        name="parse_status",
    )

    op.create_table(
        "resume_parses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("resume_id", sa.UUID(), nullable=False),
        sa.Column("resume_version", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("status", parse_status, nullable=False, server_default="PROCESSING"),
        sa.Column(
            "canonical_data",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "extraction_metadata",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
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
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resume_parses_resume_id"),
        "resume_parses",
        ["resume_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_parses_status"),
        "resume_parses",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_resume_parses_resume_id_status",
        "resume_parses",
        ["resume_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_resume_parses_resume_created",
        "resume_parses",
        ["resume_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_resume_parses_version_lookup",
        "resume_parses",
        ["resume_id", "resume_version", "parser_version", "schema_version", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_resume_parses_version_lookup", table_name="resume_parses")
    op.drop_index("ix_resume_parses_resume_created", table_name="resume_parses")
    op.drop_index("ix_resume_parses_resume_id_status", table_name="resume_parses")
    op.drop_index(op.f("ix_resume_parses_status"), table_name="resume_parses")
    op.drop_index(op.f("ix_resume_parses_resume_id"), table_name="resume_parses")
    op.drop_table("resume_parses")

    parse_status = sa.Enum(
        "PROCESSING",
        "READY",
        "FAILED",
        name="parse_status",
    )
    parse_status.drop(op.get_bind(), checkfirst=True)
