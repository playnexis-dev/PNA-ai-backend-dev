from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.arena.schemas import ArenaCreate


AdminStatus = Literal["invited", "active", "disabled"]
ManagementMode = Literal["owner", "admin"]


class AdminInviteRequest(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=150)
    confirm_conversion: bool = False


class AdminStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class AdminInviteAcceptRequest(BaseModel):
    access_token: str = Field(min_length=1)
    password: str = Field(min_length=8)
    full_name: str | None = Field(default=None, max_length=150)


class AdminArenaCreateRequest(BaseModel):
    owner_id: str = Field(min_length=1)
    arena: ArenaCreate


class ArenaManagementUpdate(BaseModel):
    management_mode: ManagementMode
    owner_id: str | None = Field(default=None, min_length=1)
