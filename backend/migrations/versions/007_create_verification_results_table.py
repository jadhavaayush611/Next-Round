"""Create verification_results and verification_evidence tables, enums, constraints, and indexes

Revision ID: 007_create_verification_results_table
Revises: 006_create_evidence_items_table
Create Date: 2026-10-21 23:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_create_verification_results_table"
down_revision: str | None = "006_create_evidence_items_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    verification_type = sa.Enum(
        "SOURCE_EXISTENCE",
        "CLAIM_SUPPORT",
        "ASSESSMENT",
        "OTHER",
        name="verification_type",
    )
    verification_outcome = sa.Enum(
        "SUPPORTED",
        "CONTRADICTED",
        "INCONCLUSIVE",
        "UNAVAILABLE",
        name="verification_outcome",
    )

    # 2. Table: verification_results
    op.create_table(
        "verification_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_claim_id", sa.UUID(), nullable=True),
        sa.Column("evidence_source_id", sa.UUID(), nullable=True),
        sa.Column("verification_type", verification_type, nullable=False),
        sa.Column("outcome", verification_outcome, nullable=False),
        sa.Column("method_version", sa.String(length=100), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "checked_at",
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
            "(candidate_claim_id IS NOT NULL OR evidence_source_id IS NOT NULL)",
            name="ck_verification_results_target_present",
        ),
        sa.CheckConstraint(
            "(verification_type != 'CLAIM_SUPPORT' OR candidate_claim_id IS NOT NULL)",
            name="ck_verification_results_claim_support_requires_claim",
        ),
        sa.CheckConstraint(
            "length(trim(method_version)) > 0",
            name="ck_verification_results_method_version_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(explanation)) > 0",
            name="ck_verification_results_explanation_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_claim_id"],
            ["candidate_claims.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_source_id"],
            ["evidence_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. Indexes on verification_results
    op.create_index(
        op.f("ix_verification_results_candidate_claim_id"),
        "verification_results",
        ["candidate_claim_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_results_evidence_source_id"),
        "verification_results",
        ["evidence_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_results_verification_type"),
        "verification_results",
        ["verification_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_results_outcome"),
        "verification_results",
        ["outcome"],
        unique=False,
    )
    op.create_index(
        "ix_verification_results_claim_created",
        "verification_results",
        ["candidate_claim_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_verification_results_source_created",
        "verification_results",
        ["evidence_source_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_verification_results_checked_at",
        "verification_results",
        ["checked_at"],
        unique=False,
    )

    # 4. Table: verification_evidence
    op.create_table(
        "verification_evidence",
        sa.Column("verification_result_id", sa.UUID(), nullable=False),
        sa.Column("evidence_item_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["verification_result_id"],
            ["verification_results.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("verification_result_id", "evidence_item_id"),
    )

    # 5. Indexes on verification_evidence
    op.create_index(
        "ix_verification_evidence_evidence_item_id",
        "verification_evidence",
        ["evidence_item_id"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop Indexes & Table: verification_evidence
    op.drop_index(
        "ix_verification_evidence_evidence_item_id",
        table_name="verification_evidence",
    )
    op.drop_table("verification_evidence")

    # 2. Drop Indexes & Table: verification_results
    op.drop_index(
        "ix_verification_results_checked_at", table_name="verification_results"
    )
    op.drop_index(
        "ix_verification_results_source_created",
        table_name="verification_results",
    )
    op.drop_index(
        "ix_verification_results_claim_created",
        table_name="verification_results",
    )
    op.drop_index(
        op.f("ix_verification_results_outcome"),
        table_name="verification_results",
    )
    op.drop_index(
        op.f("ix_verification_results_verification_type"),
        table_name="verification_results",
    )
    op.drop_index(
        op.f("ix_verification_results_evidence_source_id"),
        table_name="verification_results",
    )
    op.drop_index(
        op.f("ix_verification_results_candidate_claim_id"),
        table_name="verification_results",
    )
    op.drop_table("verification_results")

    # 3. Drop Enums
    verification_outcome = sa.Enum(
        "SUPPORTED",
        "CONTRADICTED",
        "INCONCLUSIVE",
        "UNAVAILABLE",
        name="verification_outcome",
    )
    verification_outcome.drop(op.get_bind(), checkfirst=True)

    verification_type = sa.Enum(
        "SOURCE_EXISTENCE",
        "CLAIM_SUPPORT",
        "ASSESSMENT",
        "OTHER",
        name="verification_type",
    )
    verification_type.drop(op.get_bind(), checkfirst=True)
