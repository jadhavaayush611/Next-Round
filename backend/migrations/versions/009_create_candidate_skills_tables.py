"""Create candidate_skills and candidate_skill_evidence tables, constraints, and indexes

Revision ID: 009_create_candidate_skills_tables
Revises: 008_create_skills_table
Create Date: 2026-10-25 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_create_candidate_skills_tables"
down_revision: str | None = "008_create_skills_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Table: candidate_skills
    op.create_table(
        "candidate_skills",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "skill_id", name="uq_candidate_skills_user_skill"
        ),
    )

    # Indexes on candidate_skills
    op.create_index(
        op.f("ix_candidate_skills_user_id"),
        "candidate_skills",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_skills_skill_id"),
        "candidate_skills",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_skills_user_created",
        "candidate_skills",
        ["user_id", "created_at"],
        unique=False,
    )

    # 2. Table: candidate_skill_evidence
    op.create_table(
        "candidate_skill_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_skill_id", sa.UUID(), nullable=False),
        sa.Column("candidate_claim_id", sa.UUID(), nullable=True),
        sa.Column("evidence_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "((candidate_claim_id IS NOT NULL AND evidence_item_id IS NULL) OR "
            "(candidate_claim_id IS NULL AND evidence_item_id IS NOT NULL))",
            name="ck_candidate_skill_evidence_exactly_one_source",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_skill_id"],
            ["candidate_skills.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_claim_id"],
            ["candidate_claims.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes on candidate_skill_evidence
    op.create_index(
        op.f("ix_candidate_skill_evidence_candidate_skill_id"),
        "candidate_skill_evidence",
        ["candidate_skill_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_skill_evidence_candidate_claim_id"),
        "candidate_skill_evidence",
        ["candidate_claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_skill_evidence_evidence_item_id"),
        "candidate_skill_evidence",
        ["evidence_item_id"],
        unique=False,
    )
    op.create_index(
        "uq_candidate_skill_evidence_skill_claim",
        "candidate_skill_evidence",
        ["candidate_skill_id", "candidate_claim_id"],
        unique=True,
        postgresql_where=sa.text("candidate_claim_id IS NOT NULL"),
        sqlite_where=sa.text("candidate_claim_id IS NOT NULL"),
    )
    op.create_index(
        "uq_candidate_skill_evidence_skill_item",
        "candidate_skill_evidence",
        ["candidate_skill_id", "evidence_item_id"],
        unique=True,
        postgresql_where=sa.text("evidence_item_id IS NOT NULL"),
        sqlite_where=sa.text("evidence_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    # 1. Drop Indexes & Table: candidate_skill_evidence
    op.drop_index(
        "uq_candidate_skill_evidence_skill_item",
        table_name="candidate_skill_evidence",
    )
    op.drop_index(
        "uq_candidate_skill_evidence_skill_claim",
        table_name="candidate_skill_evidence",
    )
    op.drop_index(
        op.f("ix_candidate_skill_evidence_evidence_item_id"),
        table_name="candidate_skill_evidence",
    )
    op.drop_index(
        op.f("ix_candidate_skill_evidence_candidate_claim_id"),
        table_name="candidate_skill_evidence",
    )
    op.drop_index(
        op.f("ix_candidate_skill_evidence_candidate_skill_id"),
        table_name="candidate_skill_evidence",
    )
    op.drop_table("candidate_skill_evidence")

    # 2. Drop Indexes & Table: candidate_skills
    op.drop_index(
        "ix_candidate_skills_user_created",
        table_name="candidate_skills",
    )
    op.drop_index(
        op.f("ix_candidate_skills_skill_id"),
        table_name="candidate_skills",
    )
    op.drop_index(
        op.f("ix_candidate_skills_user_id"),
        table_name="candidate_skills",
    )
    op.drop_table("candidate_skills")
