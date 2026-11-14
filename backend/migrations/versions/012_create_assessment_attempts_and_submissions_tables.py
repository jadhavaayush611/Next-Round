"""Create assessment attempts and task submissions tables, constraints, and indexes

Revision ID: 012_create_assessment_attempts_and_submissions_tables
Revises: 011_create_competencies_and_assessments_tables
Create Date: 2026-11-11 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "012_create_assessment_attempts_and_submissions_tables"
down_revision: str | None = "011_create_competencies_and_assessments_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    attempt_status = sa.Enum(
        "INITIALIZED",
        "IN_PROGRESS",
        "SUBMITTED",
        "EVALUATING",
        "EVALUATED",
        "MANUAL_REVIEW_PENDING",
        "ABANDONED",
        "EXPIRED",
        name="attempt_status",
    )
    task_submission_status = sa.Enum(
        "NOT_STARTED",
        "IN_PROGRESS",
        "COMPLETED",
        name="task_submission_status",
    )
    json_type = sa.JSON().with_variant(postgresql.JSONB, "postgresql")

    # 2. Add composite unique constraint to assessment_tasks as FK target
    with op.batch_alter_table("assessment_tasks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_assessment_tasks_id_def_id",
            ["id", "assessment_definition_id"],
        )

    # 3. Create assessment_attempts table
    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("assessment_definition_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            attempt_status,
            nullable=False,
            server_default="INITIALIZED",
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_assessment_attempts_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_definition_id"],
            ["assessment_definitions.id"],
            name="fk_assessment_attempts_definition_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_attempts"),
        sa.UniqueConstraint(
            "id",
            "assessment_definition_id",
            name="uq_assessment_attempts_id_def_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "assessment_definition_id",
            "attempt_number",
            name="uq_attempts_user_def_attempt_no",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_attempts_attempt_number_positive",
        ),
        sa.CheckConstraint(
            "submitted_at IS NULL OR started_at IS NULL OR submitted_at >= started_at",
            name="ck_attempts_submitted_after_started",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR started_at IS NULL OR expires_at >= started_at",
            name="ck_attempts_expires_after_started",
        ),
    )
    op.create_index(
        "ix_assessment_attempts_user_id",
        "assessment_attempts",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_attempts_def_id",
        "assessment_attempts",
        ["assessment_definition_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_attempts_status",
        "assessment_attempts",
        ["status"],
        unique=False,
    )

    # 4. Partial unique index: at most one active attempt per candidate per assessment version
    op.create_index(
        "uq_one_active_attempt_per_user_def",
        "assessment_attempts",
        ["user_id", "assessment_definition_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('INITIALIZED', 'IN_PROGRESS')"),
        sqlite_where=sa.text("status IN ('INITIALIZED', 'IN_PROGRESS')"),
    )

    # 5. Create task_submissions table with dual composite foreign keys
    op.create_table(
        "task_submissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("assessment_definition_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            task_submission_status,
            nullable=False,
            server_default="NOT_STARTED",
        ),
        sa.Column(
            "submission_payload",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "last_saved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_submissions"),
        sa.UniqueConstraint(
            "attempt_id",
            "task_id",
            name="uq_task_submissions_attempt_task",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "assessment_definition_id"],
            [
                "assessment_attempts.id",
                "assessment_attempts.assessment_definition_id",
            ],
            name="fk_task_submissions_attempt_def",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "assessment_definition_id"],
            [
                "assessment_tasks.id",
                "assessment_tasks.assessment_definition_id",
            ],
            name="fk_task_submissions_task_def",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_task_submissions_revision_positive",
        ),
    )
    op.create_index(
        "ix_task_submissions_attempt_id",
        "task_submissions",
        ["attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_submissions_task_id",
        "task_submissions",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop task_submissions table
    op.drop_index("ix_task_submissions_task_id", table_name="task_submissions")
    op.drop_index("ix_task_submissions_attempt_id", table_name="task_submissions")
    op.drop_table("task_submissions")

    # 2. Drop assessment_attempts table & partial index
    op.drop_index(
        "uq_one_active_attempt_per_user_def", table_name="assessment_attempts"
    )
    op.drop_index("ix_assessment_attempts_status", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_def_id", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_user_id", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")

    # 3. Drop composite unique constraint from assessment_tasks
    with op.batch_alter_table("assessment_tasks") as batch_op:
        batch_op.drop_constraint("uq_assessment_tasks_id_def_id", type_="unique")

    # 4. Drop enums
    task_submission_status = sa.Enum(
        "NOT_STARTED",
        "IN_PROGRESS",
        "COMPLETED",
        name="task_submission_status",
    )
    task_submission_status.drop(op.get_bind(), checkfirst=True)

    attempt_status = sa.Enum(
        "INITIALIZED",
        "IN_PROGRESS",
        "SUBMITTED",
        "EVALUATING",
        "EVALUATED",
        "MANUAL_REVIEW_PENDING",
        "ABANDONED",
        "EXPIRED",
        name="attempt_status",
    )
    attempt_status.drop(op.get_bind(), checkfirst=True)
