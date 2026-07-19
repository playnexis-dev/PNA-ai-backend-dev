from datetime import date, datetime, time
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field


class ArenaBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    sport: str = "Multi-sport"
    description: str = Field(min_length=1, max_length=3000)
    address: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=50)
    state: str | None = None
    country: str = "India"
    latitude: float | None = None
    longitude: float | None = None
    base_price: float = Field(default=0, ge=0)
    price_unit: str = "slot"
    amenities: list[str] = Field(min_length=1)
    images: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    contact_country_code: str = Field(pattern=r"^\+[1-9]\d{0,3}$")
    contact_number: str = Field(pattern=r"^\d{10}$")
    contact_email: EmailStr
    website: AnyHttpUrl | None = None
    instagram: str | None = Field(default=None, max_length=255)
    facebook: str | None = Field(default=None, max_length=255)
    cancellation_policy: str = Field(min_length=1, max_length=3000)
    booking_advance_percent: float = Field(gt=0, le=100)


class ArenaCreate(ArenaBase):
    pass


class ArenaUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    sport: str | None = None
    description: str | None = Field(default=None, min_length=1, max_length=3000)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    city: str | None = Field(default=None, min_length=1, max_length=50)
    state: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    base_price: float | None = Field(default=None, ge=0)
    price_unit: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    is_active: bool | None = None
    amenities: list[str] | None = Field(default=None, min_length=1)
    images: list[str] | None = None
    metadata: dict[str, Any] | None = None
    contact_country_code: str | None = Field(default=None, pattern=r"^\+[1-9]\d{0,3}$")
    contact_number: str | None = Field(default=None, pattern=r"^\d{10}$")
    contact_email: EmailStr | None = None
    website: AnyHttpUrl | None = None
    instagram: str | None = Field(default=None, max_length=255)
    facebook: str | None = Field(default=None, max_length=255)
    cancellation_policy: str | None = Field(default=None, min_length=1, max_length=3000)
    booking_advance_percent: float | None = Field(default=None, gt=0, le=100)


class SlotCreate(BaseModel):
    turf_id: str | None = None
    slot_date: date
    start_time: time
    end_time: time
    price: float = Field(default=0, ge=0)
    capacity: int = Field(default=1, gt=0)
    status: str = Field(default="active", pattern="^(active|blocked|booked)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlotUpdate(BaseModel):
    turf_id: str | None = None
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
    turf_id: str | None = None


class ArenaImageDelete(BaseModel):
    image_url: str | None = Field(default=None, min_length=1)
    media_url: str | None = Field(default=None, min_length=1)

    @property
    def url(self) -> str:
        return self.image_url or self.media_url or ""


class ArenaImagesReorder(BaseModel):
    images: list[str] = Field(min_length=1)


class TurfCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    sport: str = Field(min_length=1, max_length=50)
    sports: list[str] = Field(default_factory=list)
    shape: str = Field(min_length=1, max_length=50)
    size_unit: str = Field(min_length=1, max_length=20)
    dimension_length: float = Field(gt=0)
    dimension_width: float = Field(gt=0)
    price_per_slot: float = Field(ge=0)
    peak_surcharge: float = Field(default=0, ge=0)
    discount_amount: float = Field(default=0, ge=0)
    slot_window_minutes: int = Field(gt=0)
    peak_days: list[str] = Field(min_length=1)
    discount_days: list[str] = Field(min_length=1)
    open_time: time
    close_time: time
    size: str = Field(min_length=1, max_length=100)
    flooring: str = Field(min_length=1, max_length=100)
    used_for_more_sports: bool = False
    capacity: int = Field(default=1, gt=0)
    status: str = Field(default="active", pattern="^(active|inactive)$")
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurfUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    sport: str | None = Field(default=None, min_length=1, max_length=50)
    sports: list[str] | None = None
    shape: str | None = Field(default=None, min_length=1, max_length=50)
    size_unit: str | None = Field(default=None, min_length=1, max_length=20)
    dimension_length: float | None = Field(default=None, gt=0)
    dimension_width: float | None = Field(default=None, gt=0)
    price_per_slot: float | None = Field(default=None, ge=0)
    peak_surcharge: float | None = Field(default=None, ge=0)
    discount_amount: float | None = Field(default=None, ge=0)
    slot_window_minutes: int | None = Field(default=None, gt=0)
    peak_days: list[str] | None = None
    discount_days: list[str] | None = None
    open_time: time | None = None
    close_time: time | None = None
    size: str | None = Field(default=None, min_length=1, max_length=100)
    flooring: str | None = Field(default=None, min_length=1, max_length=100)
    used_for_more_sports: bool | None = None
    capacity: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    media: list[str] | None = None
    metadata: dict[str, Any] | None = None


class MaintenanceCreate(BaseModel):
    turf_id: str | None = None
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class MaintenanceCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
