from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=4000)
    every_minutes: int = Field(ge=1, le=43200)
    starts_at: Optional[datetime] = None

    @field_validator("title", "prompt")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain non-whitespace text")
        return value

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        return value


class ScheduleRead(BaseModel):
    id: str
    title: str
    prompt: str
    every_minutes: int
    enabled: bool
    created_at: datetime
    next_run_at: datetime


class RunRead(BaseModel):
    id: str
    schedule_id: str
    occurrence_at: datetime
    prompt: str
    status: str


class TickRequest(BaseModel):
    at: Optional[datetime] = None

    @field_validator("at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("at must include a timezone")
        return value


class TickResponse(BaseModel):
    evaluated_at: datetime
    created: List[RunRead]
    count: int
