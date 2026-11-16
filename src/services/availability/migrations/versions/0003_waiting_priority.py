from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from labreserve_messaging.events import make_event, topic_for

revision = "0003_waiting_priority"
down_revision = "0002_messaging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ["queue_generation", "drained_generation", "capacity_version"]:
        op.add_column("time_slots", sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.create_check_constraint("ck_slots_queue_versions", "time_slots", "queue_generation >= drained_generation AND drained_generation >= 0 AND capacity_version >= 0")
    op.add_column("allocations", sa.Column("queue_ticket", sa.Integer()))

    connection = op.get_bind()
    pending = connection.execute(sa.text("""
        SELECT a.booking_id, a.slot_id, a.user_id, a.attempt
        FROM allocations a
        LEFT JOIN LATERAL (
            SELECT min(o.created_at) AS first_rejection FROM outbox o
            WHERE o.payload->'data'->>'booking_id' = a.booking_id::text
              AND o.payload->>'event_type' = 'seat.rejected'
        ) history ON true
        WHERE a.status = 'REJECTED' AND a.reason = 'FULL'
          AND EXISTS (SELECT 1 FROM time_slots s WHERE s.id = a.slot_id)
        ORDER BY a.slot_id, history.first_rejection NULLS LAST, a.booking_id
    """)).mappings().all()
    counters = {}
    for row in pending:
        counters[row["slot_id"]] = counters.get(row["slot_id"], 0) + 1
        connection.execute(sa.text("UPDATE allocations SET queue_ticket = :ticket WHERE booking_id = :booking"),
            {"ticket": counters[row["slot_id"]], "booking": row["booking_id"]})
    for slot_id, generation in counters.items():
        connection.execute(sa.text("UPDATE time_slots SET queue_generation = :generation WHERE id = :slot"),
            {"generation": generation, "slot": slot_id})
    outbox = sa.table("outbox", sa.column("event_id", UUID(as_uuid=True)), sa.column("topic", sa.String()),
        sa.column("message_key", sa.String()), sa.column("payload", JSONB()))
    assigned = {}
    for row in pending:
        assigned[row["slot_id"]] = assigned.get(row["slot_id"], 0) + 1
        event = make_event("seat.rejected", "availability", {
            "booking_id": row["booking_id"], "user_id": row["user_id"], "slot_id": row["slot_id"],
            "attempt": row["attempt"], "reason": "QUEUED", "queue_ticket": assigned[row["slot_id"]],
            "queue_generation": assigned[row["slot_id"]], "capacity_version": 0,
        })
        connection.execute(outbox.insert().values(event_id=event.event_id, topic=topic_for(event),
            message_key=str(row["slot_id"]), payload=event.model_dump(mode="json")))


def downgrade() -> None:
    op.drop_column("allocations", "queue_ticket")
    op.drop_constraint("ck_slots_queue_versions", "time_slots")
    for name in ["capacity_version", "drained_generation", "queue_generation"]:
        op.drop_column("time_slots", name)
