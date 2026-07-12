from datetime import date, time
from typing import Any

from pydantic import BaseModel, Field


class ArenaBase(BaseModel):
    name: str = Field(min_length=1)
    sport: str = Field(min_length=1)
    description: str | None = None
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str | None = None
    country: str = "India"
    latitude: float | None = None
    longitude: float | None = None
    base_price: float = Field(default=0, ge=0)
    price_unit: str = "slot"
    amenities: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArenaCreate(ArenaBase):
    pass


class ArenaUpdate(BaseModel):
    name: str | None = None
    sport: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    base_price: float | None = Field(default=None, ge=0)
    price_unit: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    is_active: bool | None = None
    amenities: list[str] | None = None
    images: list[str] | None = None
    metadata: dict[str, Any] | None = None


class SlotCreate(BaseModel):
    slot_date: date
    start_time: time
    end_time: time
    price: float = Field(default=0, ge=0)
    capacity: int = Field(default=1, gt=0)
    status: str = Field(default="active", pattern="^(active|blocked|booked)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlotUpdate(BaseModel):
    slot_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    price: float | None = Field(default=None, ge=0)
    capacity: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(active|blocked|booked)$")
    metadata: dict[str, Any] | None = None


class SlotCopy(BaseModel):
    source_date: date
    target_date: date


class ArenaImageDelete(BaseModel):
    image_url: str | None = Field(default=None, min_length=1)
    media_url: str | None = Field(default=None, min_length=1)

    @property
    def url(self) -> str:
        return self.image_url or self.media_url or ""


class ArenaImagesReorder(BaseModel):
    images: list[str] = Field(min_length=1)
