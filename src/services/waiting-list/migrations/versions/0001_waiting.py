from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from labreserve_messaging import schema_v1

revision = "0001_waiting"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_v1.upgrade(op)
    op.create_table("waiting_entries",
        sa.Column("booking_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False), sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("queue_ticket", sa.Integer()), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("promotion_id", UUID(as_uuid=True)),
        sa.Column("last_failed_capacity_version", sa.Integer()),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slot_id", "queue_ticket", name="uq_waiting_slot_ticket"),
        sa.CheckConstraint("status IN ('WAITING','OFFERING','WITHDRAWING','WITHDRAWN','CONFIRMED','REJECTED')", name="ck_waiting_status"),
        sa.CheckConstraint("attempt > 0 AND (status NOT IN ('WAITING','OFFERING') OR queue_ticket IS NOT NULL)", name="ck_waiting_active_ticket"))
    op.create_index("ix_waiting_active_slot", "waiting_entries", ["slot_id", "queue_ticket"], postgresql_where=sa.text("status IN ('WAITING','OFFERING')"))
    op.create_table("slot_queues", sa.Column("slot_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("generation", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("capacity_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_drain_generation", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inflight_booking_id", UUID(as_uuid=True)))


def downgrade() -> None:
    op.drop_table("slot_queues")
    op.drop_table("waiting_entries")
    schema_v1.downgrade(op)
