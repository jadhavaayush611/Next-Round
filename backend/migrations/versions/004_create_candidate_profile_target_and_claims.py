"""Create candidate_profiles, candidate_targets, and candidate_claims tables

Revision ID: 004_create_candidate_profile_target_and_claims
Revises: 003_create_resume_parses_table
Create Date: 2026-10-11 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_create_candidate_profile_target_and_claims"
down_revision: str | None = "003_create_resume_parses_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. CandidateProfile table
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "preferred_locations",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("graduation_year", sa.Integer(), nullable=True),
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
            "graduation_year IS NULL OR (graduation_year >= 1950 AND graduation_year <= 2100)",
            name="ck_candidate_profiles_graduation_year",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_candidate_profiles_user_id"),
    )
    op.create_index(
        op.f("ix_candidate_profiles_user_id"),
        "candidate_profiles",
        ["user_id"],
        unique=True,
    )

    # 2. CandidateTarget table
    op.create_table(
        "candidate_targets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_profile_id", sa.UUID(), nullable=False),
        sa.Column("role_title", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_targets_candidate_profile_id"),
        "candidate_targets",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_targets_profile_created",
        "candidate_targets",
        ["candidate_profile_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_candidate_targets_active_profile",
        "candidate_targets",
        ["candidate_profile_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        sqlite_where=sa.text("is_active = 1"),
    )

    # 3. CandidateClaim table
    claim_type = sa.Enum(
        "SKILL",
        "PROJECT",
        "EXPERIENCE",
        "EDUCATION",
        "CERTIFICATION",
        "OTHER",
        name="claim_type",
    )
    claim_origin = sa.Enum(
        "RESUME",
        "USER_DECLARED",
        name="claim_origin",
    )

    op.create_table(
        "candidate_claims",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("resume_parse_id", sa.UUID(), nullable=True),
        sa.Column("claim_type", claim_type, nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("canonical_path", sa.String(length=500), nullable=True),
        sa.Column("origin", claim_origin, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "((origin = 'RESUME' AND resume_parse_id IS NOT NULL AND canonical_path IS NOT NULL) OR "
            "(origin = 'USER_DECLARED' AND resume_parse_id IS NULL AND canonical_path IS NULL))",
            name="ck_candidate_claims_provenance",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resume_parse_id"], ["resume_parses.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_claims_user_id"),
        "candidate_claims",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_claims_resume_parse_id"),
        "candidate_claims",
        ["resume_parse_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_claims_claim_type"),
        "candidate_claims",
        ["claim_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_claims_origin"),
        "candidate_claims",
        ["origin"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_claims_user_created",
        "candidate_claims",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # 3. Drop CandidateClaim
    op.drop_index("ix_candidate_claims_user_created", table_name="candidate_claims")
    op.drop_index(op.f("ix_candidate_claims_origin"), table_name="candidate_claims")
    op.drop_index(op.f("ix_candidate_claims_claim_type"), table_name="candidate_claims")
    op.drop_index(
        op.f("ix_candidate_claims_resume_parse_id"), table_name="candidate_claims"
    )
    op.drop_index(op.f("ix_candidate_claims_user_id"), table_name="candidate_claims")
    op.drop_table("candidate_claims")

    claim_origin = sa.Enum("RESUME", "USER_DECLARED", name="claim_origin")
    claim_origin.drop(op.get_bind(), checkfirst=True)

    claim_type = sa.Enum(
        "SKILL",
        "PROJECT",
        "EXPERIENCE",
        "EDUCATION",
        "CERTIFICATION",
        "OTHER",
        name="claim_type",
    )
    claim_type.drop(op.get_bind(), checkfirst=True)

    # 2. Drop CandidateTarget
    op.drop_index("uq_candidate_targets_active_profile", table_name="candidate_targets")
    op.drop_index(
        "ix_candidate_targets_profile_created", table_name="candidate_targets"
    )
    op.drop_index(
        op.f("ix_candidate_targets_candidate_profile_id"),
        table_name="candidate_targets",
    )
    op.drop_table("candidate_targets")

    # 1. Drop CandidateProfile
    op.drop_index(op.f("ix_candidate_profiles_user_id"), table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
