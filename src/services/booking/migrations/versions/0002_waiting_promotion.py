from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002_waiting_promotion"
down_revision = "0001_booking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("queue_ticket", sa.Integer()))
    op.add_column("bookings", sa.Column("promotion_id", UUID(as_uuid=True)))


def downgrade() -> None:
    op.drop_column("bookings", "promotion_id")
    op.drop_column("bookings", "queue_ticket")
