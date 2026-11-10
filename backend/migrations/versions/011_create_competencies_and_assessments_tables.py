"""Create competencies and assessment catalog tables, constraints, and indexes

Revision ID: 011_create_competencies_and_assessments_tables
Revises: 010_create_role_requirements_table
Create Date: 2026-11-09 20:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "011_create_competencies_and_assessments_tables"
down_revision: str | None = "010_create_role_requirements_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enums
    competency_dimension = sa.Enum(
        "KNOWLEDGE",
        "PRACTICAL_IMPLEMENTATION",
        "DEBUGGING_CODE_COMPREHENSION",
        "SYSTEM_DESIGN_TRADEOFFS",
        "TECHNICAL_COMMUNICATION",
        name="competency_dimension",
    )
    assessment_type = sa.Enum(
        "PRACTICAL_CODING",
        "SYSTEM_DESIGN",
        "CONCEPTUAL_KNOWLEDGE",
        "DEBUGGING_REVIEW",
        name="assessment_type",
    )
    assessment_difficulty = sa.Enum(
        "BEGINNER",
        "INTERMEDIATE",
        "ADVANCED",
        "EXPERT",
        name="assessment_difficulty",
    )
    assessment_status = sa.Enum(
        "DRAFT",
        "PUBLISHED",
        "DEPRECATED",
        name="assessment_status",
    )
    task_type = sa.Enum(
        "CODING",
        "MULTIPLE_CHOICE",
        "FREE_RESPONSE",
        "CODE_ANALYSIS",
        name="task_type",
    )
    evaluation_mode = sa.Enum(
        "AUTOMATED",
        "RUBRIC_MANUAL",
        "RUBRIC_SEMI_AUTOMATED",
        name="evaluation_mode",
    )

    json_type = sa.JSON().with_variant(postgresql.JSONB, "postgresql")

    # 2. Table: competencies
    op.create_table(
        "competencies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("identifier", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("dimension", competency_dimension, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="fk_competencies_skill_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_competencies"),
        sa.CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_competencies_identifier_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_competencies_name_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_competencies_description_not_empty",
        ),
    )
    op.create_index(
        "ix_competencies_identifier",
        "competencies",
        ["identifier"],
        unique=True,
    )
    op.create_index(
        "ix_competencies_skill_id",
        "competencies",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        "ix_competencies_dimension",
        "competencies",
        ["dimension"],
        unique=False,
    )
    op.create_index(
        "ix_competencies_skill_dimension",
        "competencies",
        ["skill_id", "dimension"],
        unique=False,
    )

    # 3. Table: assessment_definitions
    op.create_table(
        "assessment_definitions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("identifier", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("assessment_type", assessment_type, nullable=False),
        sa.Column("difficulty", assessment_difficulty, nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            assessment_status,
            nullable=False,
            server_default="DRAFT",
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
        sa.PrimaryKeyConstraint("id", name="pk_assessment_definitions"),
        sa.UniqueConstraint(
            "identifier",
            "version",
            name="uq_assessment_definitions_identifier_version",
        ),
        sa.CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_assessment_definitions_identifier_not_empty",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_assessment_definitions_version_positive",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assessment_definitions_title_not_empty",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_assessment_definitions_duration_positive",
        ),
    )
    op.create_index(
        "ix_assessment_definitions_identifier",
        "assessment_definitions",
        ["identifier"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_definitions_status",
        "assessment_definitions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_definitions_status_type_diff",
        "assessment_definitions",
        ["status", "assessment_type", "difficulty"],
        unique=False,
    )

    # 4. Table: assessment_tasks
    op.create_table(
        "assessment_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assessment_definition_id", sa.UUID(), nullable=False),
        sa.Column("competency_id", sa.UUID(), nullable=True),
        sa.Column("identifier", sa.String(100), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "task_metadata",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'"),
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
        sa.ForeignKeyConstraint(
            ["assessment_definition_id"],
            ["assessment_definitions.id"],
            name="fk_assessment_tasks_definition_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"],
            ["competencies.id"],
            name="fk_assessment_tasks_competency_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_tasks"),
        sa.UniqueConstraint(
            "assessment_definition_id",
            "identifier",
            name="uq_assessment_tasks_definition_identifier",
        ),
        sa.UniqueConstraint(
            "assessment_definition_id",
            "order_index",
            name="uq_assessment_tasks_definition_order",
        ),
        sa.CheckConstraint(
            "length(trim(identifier)) > 0",
            name="ck_assessment_tasks_identifier_not_empty",
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name="ck_assessment_tasks_order_index_non_negative",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assessment_tasks_title_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(prompt)) > 0",
            name="ck_assessment_tasks_prompt_not_empty",
        ),
    )
    op.create_index(
        "ix_assessment_tasks_definition_id",
        "assessment_tasks",
        ["assessment_definition_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_tasks_competency_id",
        "assessment_tasks",
        ["competency_id"],
        unique=False,
    )

    # 5. Table: evaluation_rubrics
    op.create_table(
        "evaluation_rubrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("evaluation_mode", evaluation_mode, nullable=False),
        sa.Column(
            "criteria",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "rubric_metadata",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'"),
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["assessment_tasks.id"],
            name="fk_evaluation_rubrics_task_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_rubrics"),
        sa.UniqueConstraint("task_id", name="uq_evaluation_rubrics_task_id"),
    )


def downgrade() -> None:
    # 1. Drop evaluation_rubrics
    op.drop_table("evaluation_rubrics")

    # 2. Drop assessment_tasks
    op.drop_index(
        "ix_assessment_tasks_competency_id",
        table_name="assessment_tasks",
    )
    op.drop_index(
        "ix_assessment_tasks_definition_id",
        table_name="assessment_tasks",
    )
    op.drop_table("assessment_tasks")

    # 3. Drop assessment_definitions
    op.drop_index(
        "ix_assessment_definitions_status_type_diff",
        table_name="assessment_definitions",
    )
    op.drop_index(
        "ix_assessment_definitions_status",
        table_name="assessment_definitions",
    )
    op.drop_index(
        "ix_assessment_definitions_identifier",
        table_name="assessment_definitions",
    )
    op.drop_table("assessment_definitions")

    # 4. Drop competencies
    op.drop_index(
        "ix_competencies_skill_dimension",
        table_name="competencies",
    )
    op.drop_index(
        "ix_competencies_dimension",
        table_name="competencies",
    )
    op.drop_index(
        "ix_competencies_skill_id",
        table_name="competencies",
    )
    op.drop_index(
        "ix_competencies_identifier",
        table_name="competencies",
    )
    op.drop_table("competencies")

    # 5. Drop Enums
    evaluation_mode = sa.Enum(
        "AUTOMATED",
        "RUBRIC_MANUAL",
        "RUBRIC_SEMI_AUTOMATED",
        name="evaluation_mode",
    )
    evaluation_mode.drop(op.get_bind(), checkfirst=True)

    task_type = sa.Enum(
        "CODING",
        "MULTIPLE_CHOICE",
        "FREE_RESPONSE",
        "CODE_ANALYSIS",
        name="task_type",
    )
    task_type.drop(op.get_bind(), checkfirst=True)

    assessment_status = sa.Enum(
        "DRAFT",
        "PUBLISHED",
        "DEPRECATED",
        name="assessment_status",
    )
    assessment_status.drop(op.get_bind(), checkfirst=True)

    assessment_difficulty = sa.Enum(
        "BEGINNER",
        "INTERMEDIATE",
        "ADVANCED",
        "EXPERT",
        name="assessment_difficulty",
    )
    assessment_difficulty.drop(op.get_bind(), checkfirst=True)

    assessment_type = sa.Enum(
        "PRACTICAL_CODING",
        "SYSTEM_DESIGN",
        "CONCEPTUAL_KNOWLEDGE",
        "DEBUGGING_REVIEW",
        name="assessment_type",
    )
    assessment_type.drop(op.get_bind(), checkfirst=True)

    competency_dimension = sa.Enum(
        "KNOWLEDGE",
        "PRACTICAL_IMPLEMENTATION",
        "DEBUGGING_CODE_COMPREHENSION",
        "SYSTEM_DESIGN_TRADEOFFS",
        "TECHNICAL_COMMUNICATION",
        name="competency_dimension",
    )
    competency_dimension.drop(op.get_bind(), checkfirst=True)
