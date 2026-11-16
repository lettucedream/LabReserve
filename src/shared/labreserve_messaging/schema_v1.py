import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade(op) -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("message_key", sa.String(120), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_pending", "outbox", ["id"], postgresql_where=sa.text("published_at IS NULL"))
    op.create_table(
        "inbox",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("topic", "partition", "offset", name="uq_dead_letter_position"),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade(op) -> None:
    for table in ["worker_heartbeats", "dead_letters", "inbox", "outbox"]:
        op.drop_table(table)
