from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from labreserve_messaging import schema_v1

revision = "0001_booking"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_v1.upgrade(op)
    op.create_table(
        "bookings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_booking_idempotency"),
        sa.CheckConstraint("status IN ('PENDING','CONFIRMED','WAITLISTED','CANCELLING','CANCELLED','REJECTED')", name="ck_booking_status"),
        sa.CheckConstraint("attempt > 0 AND slot_id > 0", name="ck_booking_identifiers"),
    )
    op.create_index("uq_active_user_slot", "bookings", ["user_id", "slot_id"], unique=True,
        postgresql_where=sa.text("status IN ('PENDING','CONFIRMED','WAITLISTED','CANCELLING')"))
    op.create_index("ix_booking_pending_deadline", "bookings", ["deadline_at"], postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    op.drop_table("bookings")
    schema_v1.downgrade(op)
