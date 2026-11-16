from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from labreserve_messaging.storage import DeadLetterColumns, HeartbeatColumns, InboxColumns, MessagingTables, OutboxColumns
from .database import Base

ACTIVE = ("WAITING", "OFFERING")


class WaitingEntry(Base):
    __tablename__ = "waiting_entries"
    booking_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120))
    slot_id: Mapped[int]
    queue_ticket: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int]
    promotion_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    last_failed_capacity_version: Mapped[int | None]
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("slot_id", "queue_ticket", name="uq_waiting_slot_ticket"),
        CheckConstraint("status IN ('WAITING','OFFERING','WITHDRAWING','WITHDRAWN','CONFIRMED','REJECTED')", name="ck_waiting_status"),
        CheckConstraint("attempt > 0 AND (status NOT IN ('WAITING','OFFERING') OR queue_ticket IS NOT NULL)", name="ck_waiting_active_ticket"),
        Index("ix_waiting_active_slot", "slot_id", "queue_ticket", postgresql_where=text("status IN ('WAITING','OFFERING')")),
    )

    @property
    def id(self) -> UUID:
        return self.booking_id


class SlotQueue(Base):
    __tablename__ = "slot_queues"
    slot_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    generation: Mapped[int] = mapped_column(server_default=text("0"))
    capacity_version: Mapped[int] = mapped_column(server_default=text("0"))
    last_drain_generation: Mapped[int] = mapped_column(server_default=text("0"))
    inflight_booking_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Outbox(OutboxColumns, Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_pending", "id", postgresql_where=text("published_at IS NULL")),)


class Inbox(InboxColumns, Base):
    __tablename__ = "inbox"


class DeadLetter(DeadLetterColumns, Base):
    __tablename__ = "dead_letters"
    __table_args__ = (UniqueConstraint("topic", "partition", "offset", name="uq_dead_letter_position"),)


class WorkerHeartbeat(HeartbeatColumns, Base):
    __tablename__ = "worker_heartbeats"


messaging_tables = MessagingTables(Outbox, Inbox, DeadLetter, WorkerHeartbeat)
