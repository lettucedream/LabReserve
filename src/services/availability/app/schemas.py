from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class LabCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    capacity: int = Field(gt=0, le=2147483647)


class Lab(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    name: str
    capacity: int = Field(gt=0)
    deleted_at: datetime | None = None


class TimeSlotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_interval(self) -> "TimeSlotCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("La fine deve essere successiva all'inizio")
        if self.starts_at <= datetime.now(UTC):
            raise ValueError("La fascia deve iniziare nel futuro")
        self.starts_at = self.starts_at.astimezone(UTC)
        self.ends_at = self.ends_at.astimezone(UTC)
        return self


class TimeSlot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    lab_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    available_seats: int = Field(ge=0)
    waiting_list_active: bool
