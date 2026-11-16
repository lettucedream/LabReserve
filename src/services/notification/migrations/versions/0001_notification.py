from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from labreserve_messaging import schema_v1

revision = "0001_notification"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_v1.upgrade(op)
    op.create_table("notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False), sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False), sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("booking_id", "event_type", name="uq_notification_booking_type"))
    op.create_index("ix_notifications_user_time", "notifications", ["user_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    schema_v1.downgrade(op)
