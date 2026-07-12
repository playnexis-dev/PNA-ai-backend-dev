from pydantic import (
    BaseModel,
    EmailStr,
)

from typing import Optional


class OwnerRegister(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    company_name: Optional[str] = None
    user_id: Optional[str] = None


class OwnerResponse(BaseModel):
    id: str
    user_id: Optional[str]
    full_name: str
    email: EmailStr
    phone: Optional[str]
    company_name: Optional[str]
