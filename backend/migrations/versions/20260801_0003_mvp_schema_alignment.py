"""Align authentication, camera runtime config, and zone lifecycle with MVP.

Revision ID: 20260801_0003
Revises: 20260731_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0003"
down_revision: Union[str, None] = "20260731_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _infer_source_type(source: str) -> str:
    normalized = source.strip().lower()
    if normalized.isdigit():
        return "USB"
    if normalized.startswith("rtsp://"):
        return "RTSP"
    if normalized.startswith(("http://", "https://")):
        return "HTTP"
    return "VIDEO_FILE"


def upgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.alter_column(
        "users",
        "username",
        new_column_name="gmail",
        existing_type=sa.String(50),
        type_=sa.String(254),
        existing_nullable=False,
    )
    op.execute("UPDATE users SET gmail = lower(trim(gmail)), role = 'USER'")
    op.execute("UPDATE users SET is_active = true WHERE is_active IS NULL")
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(20),
        nullable=False,
        server_default="USER",
    )
    op.alter_column(
        "users",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )
    op.create_check_constraint("ck_users_role_user", "users", "role = 'USER'")
    op.create_index("ix_users_gmail", "users", ["gmail"], unique=True)

    op.add_column("cameras", sa.Column("source_type", sa.String(20), nullable=True))
    connection = op.get_bind()
    cameras = connection.execute(sa.text("SELECT id, source FROM cameras")).mappings()
    for camera in cameras:
        connection.execute(
            sa.text("UPDATE cameras SET source_type = :source_type WHERE id = :camera_id"),
            {
                "source_type": _infer_source_type(camera["source"]),
                "camera_id": camera["id"],
            },
        )
    op.alter_column(
        "cameras", "source_type", existing_type=sa.String(20), nullable=False
    )
    op.add_column(
        "cameras",
        sa.Column("config_revision", sa.BigInteger(), server_default="1", nullable=False),
    )
    op.add_column("cameras", sa.Column("applied_revision", sa.BigInteger(), nullable=True))
    op.add_column("cameras", sa.Column("applied_zone_enabled", sa.Boolean(), nullable=True))
    op.add_column("cameras", sa.Column("applied_fall_enabled", sa.Boolean(), nullable=True))
    op.add_column("cameras", sa.Column("applied_ppe_enabled", sa.Boolean(), nullable=True))
    op.add_column(
        "cameras",
        sa.Column(
            "config_status", sa.String(20), server_default="OFFLINE", nullable=False
        ),
    )
    op.add_column("cameras", sa.Column("config_error", sa.String(1000), nullable=True))
    op.add_column(
        "cameras",
        sa.Column("config_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cameras", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE cameras SET config_status = "
        "CASE WHEN status = 'ONLINE' THEN 'PENDING' ELSE 'OFFLINE' END"
    )
    op.create_check_constraint(
        "ck_cameras_source_type",
        "cameras",
        "source_type IN ('USB', 'RTSP', 'HTTP', 'VIDEO_FILE')",
    )
    op.create_check_constraint(
        "ck_cameras_config_status",
        "cameras",
        "config_status IN ('PENDING', 'APPLIED', 'FAILED', 'OFFLINE')",
    )

    op.add_column(
        "zones", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("zones", "deleted_at")

    op.drop_constraint("ck_cameras_config_status", "cameras", type_="check")
    op.drop_constraint("ck_cameras_source_type", "cameras", type_="check")
    for column_name in (
        "last_seen_at",
        "config_applied_at",
        "config_error",
        "config_status",
        "applied_ppe_enabled",
        "applied_fall_enabled",
        "applied_zone_enabled",
        "applied_revision",
        "config_revision",
        "source_type",
    ):
        op.drop_column("cameras", column_name)

    op.drop_index("ix_users_gmail", table_name="users")
    op.drop_constraint("ck_users_role_user", "users", type_="check")
    op.execute("UPDATE users SET role = 'operator'")
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(20),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "users",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "users",
        "gmail",
        new_column_name="username",
        existing_type=sa.String(254),
        type_=sa.String(50),
        existing_nullable=False,
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
