from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from labreserve_messaging.storage import DeadLetterColumns, HeartbeatColumns, InboxColumns, MessagingTables, OutboxColumns
from .database import Base


class BookingRecord(Base):
    __tablename__ = "bookings"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(120))
    slot_id: Mapped[int]
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(server_default=text("1"))
    reason: Mapped[str | None] = mapped_column(String(80))
    queue_ticket: Mapped[int | None]
    promotion_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_booking_idempotency"),
        CheckConstraint("status IN ('PENDING','CONFIRMED','WAITLISTED','CANCELLING','CANCELLED','REJECTED')", name="ck_booking_status"),
        CheckConstraint("attempt > 0 AND slot_id > 0", name="ck_booking_identifiers"),
        Index("uq_active_user_slot", "user_id", "slot_id", unique=True,
            postgresql_where=text("status IN ('PENDING','CONFIRMED','WAITLISTED','CANCELLING')")),
        Index("ix_booking_pending_deadline", "deadline_at", postgresql_where=text("status = 'PENDING'")),
    )


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
