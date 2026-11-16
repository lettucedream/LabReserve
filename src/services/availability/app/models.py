from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from labreserve_messaging.storage import (
    DeadLetterColumns, HeartbeatColumns, InboxColumns, MessagingTables, OutboxColumns,
)


class LabRecord(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    capacity: Mapped[int]
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_labs_name", "name", unique=True, postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("capacity > 0", name="ck_labs_positive_capacity"),
        CheckConstraint("length(trim(name)) > 0", name="ck_labs_nonempty_name"),
    )


class TimeSlotRecord(Base):
    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id", ondelete="RESTRICT"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int]
    allocated_seats: Mapped[int] = mapped_column(server_default=text("0"))
    queue_generation: Mapped[int] = mapped_column(server_default=text("0"))
    drained_generation: Mapped[int] = mapped_column(server_default=text("0"))
    capacity_version: Mapped[int] = mapped_column(server_default=text("0"))

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_slots_valid_interval"),
        CheckConstraint("capacity > 0", name="ck_slots_positive_capacity"),
        CheckConstraint("queue_generation >= drained_generation AND drained_generation >= 0 AND capacity_version >= 0", name="ck_slots_queue_versions"),
        CheckConstraint(
            "allocated_seats >= 0 AND allocated_seats <= capacity",
            name="ck_slots_allocated_within_capacity",
        ),
        ExcludeConstraint(
            ("lab_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_slots_no_overlap",
            using="gist",
        ),
        Index("ix_slots_lab_start", "lab_id", "starts_at"),
    )

    @property
    def available_seats(self) -> int:
        return self.capacity - self.allocated_seats

    @property
    def waiting_list_active(self) -> bool:
        return self.queue_generation > self.drained_generation


class AllocationRecord(Base):
    __tablename__ = "allocations"
    booking_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    
    slot_id: Mapped[int]
    user_id: Mapped[str] = mapped_column(String(120))
    attempt: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(80))
    queue_ticket: Mapped[int | None]
    __table_args__ = (
        CheckConstraint("attempt > 0", name="ck_allocation_attempt"),
        CheckConstraint("status IN ('ALLOCATED','REJECTED','RELEASED')", name="ck_allocation_status"),
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
