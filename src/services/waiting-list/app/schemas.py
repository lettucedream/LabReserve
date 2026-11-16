from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WaitingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    booking_id: UUID
    user_id: str
    slot_id: int
    status: Literal["WAITING", "OFFERING", "WITHDRAWING", "WITHDRAWN", "CONFIRMED", "REJECTED"]
    position: int | None = None
    attempt: int
    enqueued_at: datetime
