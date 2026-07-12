from pydantic import (
    BaseModel,
    EmailStr,
)


class PlayerRegister(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    user_id: str | None = None
    avatar_url: str | None = None


class PlayerResponse(BaseModel):
    id: str
    user_id: str
    full_name: str
    email: EmailStr
    phone: str | None = None
    avatar_url: str | None = None
