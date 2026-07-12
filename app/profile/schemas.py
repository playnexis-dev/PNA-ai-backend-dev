from pydantic import BaseModel, Field


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    avatar_url: str | None = None
    company_name: str | None = None
