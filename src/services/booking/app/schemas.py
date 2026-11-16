from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BookingStatus = Literal["PENDING", "CONFIRMED", "WAITLISTED", "CANCELLING", "CANCELLED", "REJECTED"]


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_id: str | None = Field(default=None, min_length=1, max_length=120)
    slot_id: int = Field(gt=0, le=2147483647)


class UserDeactivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=120)


class Booking(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: str
    slot_id: int
    status: BookingStatus
    attempt: int
    reason: str | None
    deadline_at: datetime
    created_at: datetime
    updated_at: datetime
