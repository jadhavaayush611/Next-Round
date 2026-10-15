"""Create evidence_items table and associated enum, constraints, and indexes

Revision ID: 006_create_evidence_items_table
Revises: 005_create_evidence_sources_table
Create Date: 2026-10-15 19:48:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006_create_evidence_items_table"
down_revision: str | None = "005_create_evidence_sources_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    evidence_type = sa.Enum(
        "REPOSITORY_METADATA",
        "CODE_ARTIFACT",
        "DOCUMENTATION",
        "CONTRIBUTION_ACTIVITY",
        "ASSESSMENT_RESULT",
        "OTHER",
        name="evidence_type",
    )

    # 2. Table
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("evidence_source_id", sa.UUID(), nullable=False),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "observed_data",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("source_locator", sa.String(length=2048), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_evidence_items_description_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_source_id"],
            ["evidence_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. Indexes
    op.create_index(
        op.f("ix_evidence_items_evidence_source_id"),
        "evidence_items",
        ["evidence_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evidence_items_evidence_type"),
        "evidence_items",
        ["evidence_type"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_items_source_created",
        "evidence_items",
        ["evidence_source_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_items_source_observed",
        "evidence_items",
        ["evidence_source_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_items_source_type",
        "evidence_items",
        ["evidence_source_id", "evidence_type"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index("ix_evidence_items_source_type", table_name="evidence_items")
    op.drop_index("ix_evidence_items_source_observed", table_name="evidence_items")
    op.drop_index("ix_evidence_items_source_created", table_name="evidence_items")
    op.drop_index(op.f("ix_evidence_items_evidence_type"), table_name="evidence_items")
    op.drop_index(
        op.f("ix_evidence_items_evidence_source_id"), table_name="evidence_items"
    )

    # 2. Drop Table
    op.drop_table("evidence_items")

    # 3. Drop Enum
    evidence_type = sa.Enum(
        "REPOSITORY_METADATA",
        "CODE_ARTIFACT",
        "DOCUMENTATION",
        "CONTRIBUTION_ACTIVITY",
        "ASSESSMENT_RESULT",
        "OTHER",
        name="evidence_type",
    )
    evidence_type.drop(op.get_bind(), checkfirst=True)
