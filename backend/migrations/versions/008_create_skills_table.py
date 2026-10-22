"""Create skills table and associated constraints and indexes

Revision ID: 008_create_skills_table
Revises: 007_create_verification_results_table
Create Date: 2026-10-22 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "008_create_skills_table"
down_revision: str | None = "007_create_verification_results_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Table: skills
    op.create_table(
        "skills",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column(
            "aliases",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
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
        sa.CheckConstraint(
            "length(trim(canonical_name)) > 0",
            name="ck_skills_canonical_name_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(category)) > 0",
            name="ck_skills_category_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name", name="uq_skills_canonical_name"),
    )

    # 2. Indexes
    op.create_index(
        op.f("ix_skills_canonical_name"), "skills", ["canonical_name"], unique=True
    )
    op.create_index(
        op.f("ix_skills_category"), "skills", ["category"], unique=False
    )
    op.create_index(
        "uq_skills_canonical_name_lower",
        "skills",
        [sa.text("lower(trim(canonical_name))")],
        unique=True,
    )


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index("uq_skills_canonical_name_lower", table_name="skills")
    op.drop_index(op.f("ix_skills_category"), table_name="skills")
    op.drop_index(op.f("ix_skills_canonical_name"), table_name="skills")

    # 2. Drop Table
    op.drop_table("skills")
