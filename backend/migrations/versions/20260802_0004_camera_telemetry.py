"""Add latest camera telemetry snapshot.

Revision ID: 20260802_0004
Revises: 20260801_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_0004"
down_revision = "20260801_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("processing_fps", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("latency_ms", sa.Float(), nullable=True))
    op.add_column(
        "cameras", sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("cameras", "last_frame_at")
    op.drop_column("cameras", "latency_ms")
    op.drop_column("cameras", "processing_fps")
