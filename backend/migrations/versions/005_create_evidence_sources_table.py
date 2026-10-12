"""Create evidence_sources table and associated enums and indexes

Revision ID: 005_create_evidence_sources_table
Revises: 004_create_candidate_profile_target_and_claims
Create Date: 2026-10-12 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_create_evidence_sources_table"
down_revision: str | None = "004_create_candidate_profile_target_and_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    evidence_source_type = sa.Enum(
        "GITHUB_REPOSITORY",
        "GITHUB_PROFILE",
        "LINKEDIN_PROFILE",
        "PORTFOLIO",
        "ASSESSMENT",
        "OTHER",
        name="evidence_source_type",
    )
    access_mode = sa.Enum(
        "PUBLIC",
        "AUTHORIZED",
        "INTERNAL",
        name="access_mode",
    )
    evidence_source_status = sa.Enum(
        "AVAILABLE",
        "INACCESSIBLE",
        "REVOKED",
        "ERROR",
        "NOT_CHECKED",
        name="evidence_source_status",
    )

    # 2. Table
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_type", evidence_source_type, nullable=False),
        sa.Column("source_uri", sa.String(length=2048), nullable=False),
        sa.Column(
            "access_mode",
            access_mode,
            nullable=False,
            server_default="PUBLIC",
        ),
        sa.Column(
            "access_status",
            evidence_source_status,
            nullable=False,
            server_default="NOT_CHECKED",
        ),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_uri", name="uq_evidence_sources_user_uri"),
    )

    # 3. Indexes
    op.create_index(
        op.f("ix_evidence_sources_user_id"),
        "evidence_sources",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evidence_sources_source_type"),
        "evidence_sources",
        ["source_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evidence_sources_access_status"),
        "evidence_sources",
        ["access_status"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_sources_user_created",
        "evidence_sources",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_sources_user_type",
        "evidence_sources",
        ["user_id", "source_type"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_sources_user_status",
        "evidence_sources",
        ["user_id", "access_status"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index("ix_evidence_sources_user_status", table_name="evidence_sources")
    op.drop_index("ix_evidence_sources_user_type", table_name="evidence_sources")
    op.drop_index("ix_evidence_sources_user_created", table_name="evidence_sources")
    op.drop_index(
        op.f("ix_evidence_sources_access_status"), table_name="evidence_sources"
    )
    op.drop_index(
        op.f("ix_evidence_sources_source_type"), table_name="evidence_sources"
    )
    op.drop_index(op.f("ix_evidence_sources_user_id"), table_name="evidence_sources")

    # 2. Drop Table
    op.drop_table("evidence_sources")

    # 3. Drop Enums (PostgreSQL conditional)
    evidence_source_status = sa.Enum(
        "AVAILABLE",
        "INACCESSIBLE",
        "REVOKED",
        "ERROR",
        "NOT_CHECKED",
        name="evidence_source_status",
    )
    evidence_source_status.drop(op.get_bind(), checkfirst=True)

    access_mode = sa.Enum(
        "PUBLIC",
        "AUTHORIZED",
        "INTERNAL",
        name="access_mode",
    )
    access_mode.drop(op.get_bind(), checkfirst=True)

    evidence_source_type = sa.Enum(
        "GITHUB_REPOSITORY",
        "GITHUB_PROFILE",
        "LINKEDIN_PROFILE",
        "PORTFOLIO",
        "ASSESSMENT",
        "OTHER",
        name="evidence_source_type",
    )
    evidence_source_type.drop(op.get_bind(), checkfirst=True)
