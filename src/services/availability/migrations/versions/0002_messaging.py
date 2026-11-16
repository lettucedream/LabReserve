from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from labreserve_messaging import schema_v1

revision = "0002_messaging"
down_revision = "0001_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_v1.upgrade(op)
    op.create_table(
        "allocations",
        sa.Column("booking_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.CheckConstraint("attempt > 0", name="ck_allocation_attempt"),
        sa.CheckConstraint("status IN ('ALLOCATED','REJECTED','RELEASED')", name="ck_allocation_status"),
    )


def downgrade() -> None:
    op.drop_table("allocations")
    schema_v1.downgrade(op)
