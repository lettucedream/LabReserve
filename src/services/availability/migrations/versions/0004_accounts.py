from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_accounts"
down_revision = "0003_waiting_priority"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False, unique=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("role", sa.String(10), nullable=False, server_default="user"),
        sa.Column("password_hash", sa.String(256)), sa.Column("recovery_hash", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_accounts_role"))
    op.create_index("uq_accounts_one_admin", "accounts", ["role"], unique=True, postgresql_where=sa.text("role = 'admin'"))
    op.create_table("account_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])
    op.create_table("auth_throttle", sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("window_until", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("auth_throttle")
    op.drop_table("account_sessions")
    op.drop_table("accounts")
