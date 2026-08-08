"""Add additive SaaS control-plane entities.

The existing customer-host users/cameras remain intact. This migration adds
device-authenticated cloud records without changing model or event payloads.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260808_0005"
down_revision: Union[str, None] = "20260802_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing customer-host records are left nullable until an enrollment
    # operation assigns them to a tenant/device.
    op.add_column("cameras", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("cameras", sa.Column("edge_device_id", sa.Integer(), nullable=True))
    op.add_column("cameras", sa.Column("stream_id", sa.Integer(), nullable=True))
    op.add_column("violations", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("system_events", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("evidence_objects", sa.Column("tenant_id", sa.Integer(), nullable=True))

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key"),
    )
    op.create_index("ix_tenants_tenant_key", "tenants", ["tenant_key"], unique=True)
    op.create_table(
        "edge_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OFFLINE"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_key", name="uq_edge_device_tenant_key"),
    )
    op.create_index("ix_edge_devices_tenant_id", "edge_devices", ["tenant_id"])
    op.create_table(
        "device_credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False, server_default="default"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["edge_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_device_credentials_device_id", "device_credentials", ["device_id"])
    op.create_index("ix_device_credentials_token_hash", "device_credentials", ["token_hash"], unique=True)
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("camera_key", sa.String(100), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False, server_default="RTSP"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OFFLINE"),
        sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["edge_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "path", name="uq_stream_tenant_path"),
    )
    op.create_index("ix_streams_tenant_id", "streams", ["tenant_id"])
    op.create_index("ix_streams_device_id", "streams", ["device_id"])
    op.create_table(
        "camera_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model_toggles", sa.JSON(), nullable=False),
        sa.Column("operational_config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_camera_profiles_tenant_id", "camera_profiles", ["tenant_id"])
    op.create_table(
        "model_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["camera_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_assignments_tenant_id", "model_assignments", ["tenant_id"])
    op.create_index("ix_model_assignments_profile_id", "model_assignments", ["profile_id"])
    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("camera_key", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(150), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["edge_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_event_deliveries_tenant_id", "event_deliveries", ["tenant_id"])
    op.create_index("ix_event_deliveries_device_id", "event_deliveries", ["device_id"])
    op.create_index("ix_event_deliveries_idempotency_key", "event_deliveries", ["idempotency_key"], unique=True)
    op.create_foreign_key("fk_cameras_tenant_id", "cameras", "tenants", ["tenant_id"], ["id"])
    op.create_foreign_key("fk_cameras_edge_device_id", "cameras", "edge_devices", ["edge_device_id"], ["id"])
    op.create_foreign_key("fk_cameras_stream_id", "cameras", "streams", ["stream_id"], ["id"])
    op.create_foreign_key("fk_violations_tenant_id", "violations", "tenants", ["tenant_id"], ["id"])
    op.create_foreign_key("fk_system_events_tenant_id", "system_events", "tenants", ["tenant_id"], ["id"])
    op.create_foreign_key("fk_evidence_objects_tenant_id", "evidence_objects", "tenants", ["tenant_id"], ["id"])


def downgrade() -> None:
    for name, table in (
        ("fk_evidence_objects_tenant_id", "evidence_objects"),
        ("fk_system_events_tenant_id", "system_events"),
        ("fk_violations_tenant_id", "violations"),
        ("fk_cameras_stream_id", "cameras"),
        ("fk_cameras_edge_device_id", "cameras"),
        ("fk_cameras_tenant_id", "cameras"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    for table in ("event_deliveries", "model_assignments", "camera_profiles", "streams", "device_credentials", "edge_devices", "tenants"):
        op.drop_table(table)
    op.drop_column("evidence_objects", "tenant_id")
    op.drop_column("system_events", "tenant_id")
    op.drop_column("violations", "tenant_id")
    op.drop_column("cameras", "stream_id")
    op.drop_column("cameras", "edge_device_id")
    op.drop_column("cameras", "tenant_id")
