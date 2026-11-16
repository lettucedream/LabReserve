from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from labreserve_messaging.storage import DeadLetterColumns, HeartbeatColumns, InboxColumns, MessagingTables, OutboxColumns
from .database import Base


class NotificationRecord(Base):
    __tablename__ = "notifications"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[str] = mapped_column(String(120))
    slot_id: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    source_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("booking_id", "event_type", name="uq_notification_booking_type"),
        Index("ix_notifications_user_time", "user_id", "occurred_at"),
    )


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
