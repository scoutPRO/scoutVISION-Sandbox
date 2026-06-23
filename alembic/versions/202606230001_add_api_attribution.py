"""Add API attribution fields to prompt runs.

Revision ID: 202606230001
Revises: 202605200002
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202606230001"
down_revision: str | None = "202605200002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add external attribution fields for scoutSMART API calls."""
    with op.batch_alter_table("prompt_runs") as batch_op:
        batch_op.add_column(sa.Column("external_account_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("external_user_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("integration_source", sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Remove external attribution fields."""
    with op.batch_alter_table("prompt_runs") as batch_op:
        batch_op.drop_column("integration_source")
        batch_op.drop_column("external_user_id")
        batch_op.drop_column("external_account_id")
