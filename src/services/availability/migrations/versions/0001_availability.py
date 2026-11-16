from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision = "0001_availability"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "labs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.UniqueConstraint("name", name="uq_labs_name"),
        sa.CheckConstraint("capacity > 0", name="ck_labs_positive_capacity"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_labs_nonempty_name"),
    )
    op.create_table(
        "time_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lab_id", sa.Integer(), sa.ForeignKey("labs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("allocated_seats", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_slots_valid_interval"),
        sa.CheckConstraint("capacity > 0", name="ck_slots_positive_capacity"),
        sa.CheckConstraint("allocated_seats >= 0 AND allocated_seats <= capacity", name="ck_slots_allocated_within_capacity"),
        ExcludeConstraint(
            ("lab_id", "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_slots_no_overlap",
            using="gist",
        ),
    )
    op.create_index("ix_slots_lab_start", "time_slots", ["lab_id", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_slots_lab_start", table_name="time_slots")
    op.drop_table("time_slots")
    op.drop_table("labs")
