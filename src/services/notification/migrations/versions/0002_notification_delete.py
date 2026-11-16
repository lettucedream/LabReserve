from alembic import op
import sqlalchemy as sa

revision = "0002_notification_delete"
down_revision = "0001_notification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("notifications", "deleted_at")
