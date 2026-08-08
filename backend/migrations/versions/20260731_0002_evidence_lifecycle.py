"""Add direct-to-object-storage evidence upload lifecycle metadata."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260731_0002"
down_revision: Union[str, None] = "20260731_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("evidence_objects", "object_key", existing_type=sa.String(1024), nullable=False)
    op.add_column("evidence_objects", sa.Column("failure_reason", sa.String(1000), nullable=True))
    op.add_column("evidence_objects", sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "evidence_objects",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_evidence_violation_kind", "evidence_objects", ["violation_id", "kind"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_evidence_violation_kind", "evidence_objects", type_="unique")
    op.drop_column("evidence_objects", "updated_at")
    op.drop_column("evidence_objects", "upload_expires_at")
    op.drop_column("evidence_objects", "failure_reason")
    op.alter_column("evidence_objects", "object_key", existing_type=sa.String(1024), nullable=True)
