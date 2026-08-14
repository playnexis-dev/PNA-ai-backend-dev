from typing import (Literal, Optional)

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
)


UserRole = Literal["player", "owner", "admin"]
SignupRole = Literal["player", "owner"]

class OAuthCompleteRequest(BaseModel):
    role: SignupRole
    full_name: Optional[str] = None
    phone: Optional[str] = None
    company_name: Optional[str] = None


class PhoneOtpSendRequest(BaseModel):
    role: SignupRole
    phone: str = Field(min_length=8, max_length=20)


class PhoneOtpVerifyRequest(BaseModel):
    role: SignupRole
    phone: str = Field(min_length=8, max_length=20)
    code: str = Field(min_length=4, max_length=8)

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    role: Literal["player"]
    full_name: str = Field(min_length=1)
    phone: str = Field(min_length=8, max_length=20)
    company_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshSessionRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class GoogleSessionRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None
    role: SignupRole


class GoogleCodeRequest(BaseModel):
    code: str
    state: str
    role: SignupRole
