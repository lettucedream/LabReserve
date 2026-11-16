from alembic import op
import sqlalchemy as sa

revision = "0006_lab_removal"
down_revision = "0005_account_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("labs", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.drop_constraint("uq_labs_name", "labs", type_="unique")
    op.create_index("uq_labs_name", "labs", ["name"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade():
    
    
    op.execute("UPDATE labs SET name = left(name, 90) || ' [rimosso #' || id || ']' WHERE deleted_at IS NOT NULL")
    op.drop_index("uq_labs_name", table_name="labs")
    op.create_unique_constraint("uq_labs_name", "labs", ["name"])
    op.drop_column("labs", "deleted_at")
