from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .events import Event, topic_for


class OutboxColumns:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    topic: Mapped[str] = mapped_column(String(120))
    message_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxColumns:
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadLetterColumns:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    topic: Mapped[str] = mapped_column(String(120))
    partition: Mapped[int]
    offset: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HeartbeatColumns:
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class MessagingTables:
    outbox: type
    inbox: type
    dead_letter: type
    heartbeat: type


def enqueue(session, outbox_model: type, event: Event) -> None:
    session.add(outbox_model(
        event_id=event.event_id, topic=topic_for(event), message_key=str(event.data.slot_id),
        payload=event.model_dump(mode="json"),
    ))
