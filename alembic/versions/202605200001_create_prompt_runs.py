"""Create prompt runs table.

Revision ID: 202605200001
Revises:
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605200001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the prompt_runs table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "prompt_runs" in inspector.get_table_names():
        return

    op.create_table(
        "prompt_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("video_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_video_path", sa.Text(), nullable=False),
        sa.Column("video_duration_seconds", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("boilerplate_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("full_prompt", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("parsed_response_json", sa.Text(), nullable=True),
        sa.Column("full_response_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("feedback_rating", sa.String(length=20), nullable=True),
        sa.Column("feedback_notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop the prompt_runs table."""
    op.drop_table("prompt_runs")
