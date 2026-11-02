"""Create role_requirements table, constraints, and indexes

Revision ID: 010_create_role_requirements_table
Revises: 009_create_candidate_skills_tables
Create Date: 2026-10-25 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_create_role_requirements_table"
down_revision: str | None = "009_create_candidate_skills_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    requirement_type = sa.Enum(
        "SKILL",
        "QUALIFICATION",
        "EXPERIENCE",
        "OTHER",
        name="requirement_type",
    )
    requirement_importance = sa.Enum(
        "REQUIRED",
        "PREFERRED",
        "UNSPECIFIED",
        name="requirement_importance",
    )
    requirement_source_type = sa.Enum(
        "JOB_DESCRIPTION",
        "CURATED_ROLE",
        name="requirement_source_type",
    )

    # 2. Table: role_requirements
    op.create_table(
        "role_requirements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_target_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=True),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("requirement_type", requirement_type, nullable=False),
        sa.Column("importance", requirement_importance, nullable=False),
        sa.Column("source_type", requirement_source_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_target_id"],
            ["candidate_targets.id"],
            name="fk_role_requirements_candidate_target_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="fk_role_requirements_skill_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_requirements"),
        sa.CheckConstraint(
            "length(trim(requirement_text)) > 0",
            name="ck_role_requirements_text_not_empty",
        ),
    )

    # 3. Indexes
    op.create_index(
        "ix_role_requirements_candidate_target_id",
        "role_requirements",
        ["candidate_target_id"],
        unique=False,
    )
    op.create_index(
        "ix_role_requirements_skill_id",
        "role_requirements",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        "ix_role_requirements_target_created",
        "role_requirements",
        ["candidate_target_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index(
        "ix_role_requirements_target_created",
        table_name="role_requirements",
    )
    op.drop_index(
        "ix_role_requirements_skill_id",
        table_name="role_requirements",
    )
    op.drop_index(
        "ix_role_requirements_candidate_target_id",
        table_name="role_requirements",
    )

    # 2. Drop Table
    op.drop_table("role_requirements")

    # 3. Drop Enums
    requirement_source_type = sa.Enum(
        "JOB_DESCRIPTION",
        "CURATED_ROLE",
        name="requirement_source_type",
    )
    requirement_source_type.drop(op.get_bind(), checkfirst=True)

    requirement_importance = sa.Enum(
        "REQUIRED",
        "PREFERRED",
        "UNSPECIFIED",
        name="requirement_importance",
    )
    requirement_importance.drop(op.get_bind(), checkfirst=True)

    requirement_type = sa.Enum(
        "SKILL",
        "QUALIFICATION",
        "EXPERIENCE",
        "OTHER",
        name="requirement_type",
    )
    requirement_type.drop(op.get_bind(), checkfirst=True)
