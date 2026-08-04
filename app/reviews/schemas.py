from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    booking_id: str | None = None
    arena_id: str | None = None
    rating: int = Field(ge=1, le=5)
    comment: str | None = None
