"""Add users and prompt run ownership.

Revision ID: 202605200002
Revises: 202605200001
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605200002"
down_revision: str | None = "202605200001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create users table and add prompt run ownership."""
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    with op.batch_alter_table("prompt_runs") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_prompt_runs_user_id_users",
            "users",
            ["user_id"],
            ["id"],
        )


def downgrade() -> None:
    """Remove prompt run ownership and users table."""
    with op.batch_alter_table("prompt_runs") as batch_op:
        batch_op.drop_constraint("fk_prompt_runs_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    op.drop_table("users")
