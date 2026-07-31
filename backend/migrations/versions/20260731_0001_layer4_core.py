"""Create Layer 4 core tables aligned with typed AI events."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260731_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("camera_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("location_desc", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), server_default="OFFLINE", nullable=False),
        sa.Column("zone_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("fall_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("ppe_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_key"),
    )
    op.create_index("ix_cameras_camera_key", "cameras", ["camera_key"], unique=True)
    op.create_index("ix_cameras_status", "cameras", ["status"], unique=False)

    op.create_table(
        "zones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("polygon_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_zones_camera_id", "zones", ["camera_id"], unique=False)

    op.create_table(
        "violations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.String(150), nullable=False),
        sa.Column("detected_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("violation_type", sa.String(50), nullable=False),
        sa.Column("severity_level", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("zone_id", sa.Integer(), nullable=True),
        sa.Column("violation_codes", sa.JSON(), nullable=True),
        sa.Column("evidence_status", sa.String(20), server_default="PROCESSING", nullable=False),
        sa.Column("image_storage_key", sa.String(1024), nullable=True),
        sa.Column("video_storage_key", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(20), server_default="NEW", nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    for name, columns in (
        ("ix_violations_event_id", ["event_id"]),
        ("ix_violations_camera_id", ["camera_id"]),
        ("ix_violations_track_id", ["track_id"]),
        ("ix_violations_detected_time", ["detected_time"]),
        ("ix_violations_violation_type", ["violation_type"]),
        ("ix_violations_severity_level", ["severity_level"]),
        ("ix_violations_zone_id", ["zone_id"]),
        ("ix_violations_status", ["status"]),
    ):
        op.create_index(name, "violations", columns, unique=name == "ix_violations_event_id")

    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("source", sa.String(100), server_default="SUPERVISOR", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_system_events_event_id", "system_events", ["event_id"], unique=True)
    op.create_index("ix_system_events_camera_id", "system_events", ["camera_id"], unique=False)
    op.create_index("ix_system_events_observed_at", "system_events", ["observed_at"], unique=False)

    op.create_table(
        "evidence_objects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("violation_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(20), server_default="PROCESSING", nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["violation_id"], ["violations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_evidence_objects_violation_id", "evidence_objects", ["violation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidence_objects_violation_id", table_name="evidence_objects")
    op.drop_table("evidence_objects")
    op.drop_index("ix_system_events_observed_at", table_name="system_events")
    op.drop_index("ix_system_events_camera_id", table_name="system_events")
    op.drop_index("ix_system_events_event_id", table_name="system_events")
    op.drop_table("system_events")
    for name in (
        "ix_violations_status",
        "ix_violations_zone_id",
        "ix_violations_severity_level",
        "ix_violations_violation_type",
        "ix_violations_detected_time",
        "ix_violations_track_id",
        "ix_violations_camera_id",
        "ix_violations_event_id",
    ):
        op.drop_index(name, table_name="violations")
    op.drop_table("violations")
    op.drop_index("ix_zones_camera_id", table_name="zones")
    op.drop_table("zones")
    op.drop_index("ix_cameras_status", table_name="cameras")
    op.drop_index("ix_cameras_camera_key", table_name="cameras")
    op.drop_table("cameras")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
