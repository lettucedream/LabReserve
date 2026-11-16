from alembic import op
import sqlalchemy as sa

revision = "0003_blocked_users"
down_revision = "0002_waiting_promotion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("blocked_users",
        sa.Column("user_id", sa.String(120), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.drop_table("blocked_users")
