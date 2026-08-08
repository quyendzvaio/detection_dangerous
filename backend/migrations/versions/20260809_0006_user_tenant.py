"""Multi-tenant isolation: users and zones get tenant_id.

Adds users.tenant_id and zones.tenant_id (both NOT NULL), backfills all
existing NULL tenant_id rows (users/cameras/violations/system_events/
evidence_objects/zones) into a default "cloud" tenant, so every row belongs
to exactly one tenant after this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0006"
down_revision: Union[str, None] = "20260808_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cloud_tenant_id(connection) -> int:
    """Create the default 'cloud' tenant if absent and return its id."""
    connection.execute(
        sa.text(
            "INSERT INTO tenants (tenant_key, name) "
            "SELECT 'cloud', 'cloud' "
            "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE tenant_key = 'cloud')"
        )
    )
    row = connection.execute(
        sa.text("SELECT id FROM tenants WHERE tenant_key = 'cloud'")
    ).scalar_one()
    return int(row)


def upgrade() -> None:
    connection = op.get_bind()

    # 1. users.tenant_id — nullable first so backfill can run.
    op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    cloud_id = _cloud_tenant_id(connection)

    # 2. Backfill every NULL tenant_id into the default tenant.
    for table in ("users", "cameras", "violations", "system_events", "evidence_objects"):
        connection.execute(
            sa.text(f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL").bindparams(
                tid=cloud_id
            )
        )

    # 3. users.tenant_id NOT NULL + FK.
    op.alter_column("users", "tenant_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("fk_users_tenant_id", "users", "tenants", ["tenant_id"], ["id"])

    # 4. zones.tenant_id — nullable, backfill from owning camera, then NOT NULL.
    op.add_column("zones", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_index("ix_zones_tenant_id", "zones", ["tenant_id"])
    connection.execute(
        sa.text(
            "UPDATE zones SET tenant_id = "
            "(SELECT cameras.tenant_id FROM cameras WHERE cameras.id = zones.camera_id) "
            "WHERE tenant_id IS NULL"
        )
    )
    # Orphan zones (camera missing) fall back to the default tenant.
    connection.execute(
        sa.text("UPDATE zones SET tenant_id = :tid WHERE tenant_id IS NULL").bindparams(
            tid=cloud_id
        )
    )
    op.alter_column("zones", "tenant_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("fk_zones_tenant_id", "zones", "tenants", ["tenant_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_zones_tenant_id", "zones", type_="foreignkey")
    op.drop_index("ix_zones_tenant_id", table_name="zones")
    op.drop_column("zones", "tenant_id")
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "tenant_id")
