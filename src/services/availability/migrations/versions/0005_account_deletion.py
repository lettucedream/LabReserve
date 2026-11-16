from alembic import op
import sqlalchemy as sa

revision = "0005_account_deletion"
down_revision = "0004_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.drop_constraint("accounts_username_key", "accounts", type_="unique")
    op.create_index("uq_accounts_active_username", "accounts", ["username"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade():
    
    op.execute("DELETE FROM accounts WHERE deleted_at IS NOT NULL")
    op.drop_index("uq_accounts_active_username", table_name="accounts")
    op.create_unique_constraint("accounts_username_key", "accounts", ["username"])
    op.drop_column("accounts", "deleted_at")
