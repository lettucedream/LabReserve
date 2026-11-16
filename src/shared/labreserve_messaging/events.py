from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

COMMANDS = "labreserve.availability.commands.v1"
AVAILABILITY_EVENTS = "labreserve.availability.events.v1"
BOOKING_EVENTS = "labreserve.booking.events.v1"
WAITING_COMMANDS = "labreserve.waiting.commands.v1"
BOOKING_COMMANDS = "labreserve.booking.commands.v1"

EventType = Literal[
    "seat.reserve", "seat.release", "seat.reserved", "seat.rejected", "seat.released", "seat.revoked",
    "booking.confirmed", "booking.waitlisted", "booking.rejected", "booking.cancelled",
    "waiting.promote", "waiting.withdraw", "waiting.withdraw_requested", "queue.drain",
    "booking.promotion_skipped",
]


class EventData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    booking_id: UUID
    user_id: str = Field(min_length=1, max_length=120)
    slot_id: int = Field(gt=0, le=2147483647)
    attempt: int = Field(default=1, gt=0)
    reason: str | None = Field(default=None, max_length=80)
    queue_ticket: int | None = Field(default=None, gt=0)
    queue_generation: int = Field(default=0, ge=0)
    capacity_version: int = Field(default=0, ge=0)
    promotion_id: UUID | None = None


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    event_type: EventType
    schema_version: Literal[1] = 1
    occurred_at: AwareDatetime
    producer: Literal["booking", "availability", "waiting-list", "notification"]
    correlation_id: UUID
    causation_id: UUID | None = None
    data: EventData

    @model_validator(mode="after")
    def validate_correlation(self) -> "Event":
        if self.correlation_id != self.data.booking_id:
            raise ValueError("correlation_id deve corrispondere alla prenotazione")
        return self


def make_event(event_type: EventType, producer: str, data: dict | EventData, cause: UUID | None = None) -> Event:
    payload = data if isinstance(data, EventData) else EventData.model_validate(data)
    return Event(
        event_id=uuid4(), event_type=event_type, occurred_at=datetime.now(UTC),
        producer=producer, correlation_id=payload.booking_id, causation_id=cause, data=payload,
    )


def topic_for(event: Event) -> str:
    if event.event_type in {"seat.reserve", "seat.release", "queue.drain"}:
        return COMMANDS
    if event.event_type == "waiting.withdraw":
        return WAITING_COMMANDS
    if event.event_type in {"waiting.promote", "waiting.withdraw_requested"}:
        return BOOKING_COMMANDS
    if event.event_type.startswith("seat."):
        return AVAILABILITY_EVENTS
    return BOOKING_EVENTS
