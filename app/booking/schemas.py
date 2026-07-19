from datetime import date, time
from typing import Any

from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    arena_id: str
    turf_id: str | None = None
    slot_id: str | None = None
    slot_ids: list[str] = Field(default_factory=list)
    booking_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    sport: str | None = None
    total_amount: float | None = Field(default=None, ge=0)
    notes: str | None = None
    simulate_payment: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BookingStatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|confirmed|rejected|completed|cancelled)$")


class PaymentCreate(BaseModel):
    amount: float | None = Field(default=None, ge=0)
    provider_reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
