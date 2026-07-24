"""Refactor users table to lean core entity (add username, role, is_active, updated_at; drop placement fields)

Revision ID: 001_add_user_profile_fields
Revises:
Create Date: 2026-07-24 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_add_user_profile_fields"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=50), nullable=False, server_default="user"),
    )
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # Drop placement fields from core User entity
    for col in ("college", "graduation_year", "branch", "cgpa", "target_role"):
        try:
            op.drop_column("users", col)
        except Exception:
            pass


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("target_role", sa.String(length=255), nullable=True)
    )
    op.add_column("users", sa.Column("cgpa", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("branch", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("graduation_year", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("college", sa.String(length=255), nullable=True))
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_column("users", "username")
