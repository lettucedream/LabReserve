from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Notification(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    booking_id: UUID
    user_id: str
    slot_id: int
    event_type: str
    message: str
    occurred_at: datetime
    created_at: datetime
    read_at: datetime | None


class ReadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_read: bool
