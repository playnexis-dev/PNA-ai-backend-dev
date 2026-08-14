from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Header, HTTPException

from app.core.supabase import get_supabase_client, supabase

UserRole = Literal["player", "owner", "admin"]


@dataclass
class AuthContext:
    access_token: str
    user: Any
    role: UserRole
    profile: dict | None


def get_bearer_token(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    return token


def normalize_phone(phone: str | None):
    if phone is None:
        return None

    digits = "".join(ch for ch in phone.strip() if ch.isdigit())
    return digits or None


def get_current_auth_context(
    authorization: str | None = Header(default=None),
):
    token = get_bearer_token(authorization)
    user_response = supabase.auth.get_user(token)

    if not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    client = get_supabase_client(token)
    role_response = (
        client.table("user_roles")
        .select("role")
        .eq("user_id", user_response.user.id)
        .maybe_single()
        .execute()
    )

    if not role_response or not role_response.data:
        raise HTTPException(status_code=403, detail="User role not found")

    role = role_response.data.get("role")
    if role not in ("player", "owner", "admin"):
        raise HTTPException(status_code=403, detail="Invalid user role")

    table = {
        "player": "players",
        "owner": "owners",
        "admin": "admins",
    }[role]
    profile_response = (
        client.table(table)
        .select("*")
        .eq("user_id", user_response.user.id)
        .maybe_single()
        .execute()
    )

    profile = profile_response.data if profile_response else None
    if role == "admin" and (not profile or profile.get("status") != "active"):
        raise HTTPException(status_code=403, detail="Admin account is not active")

    return AuthContext(
        access_token=token,
        user=user_response.user,
        role=role,
        profile=profile,
    )


def get_optional_auth_context(
    authorization: str | None = Header(default=None),
):
    if not authorization:
        return None
    return get_current_auth_context(authorization)


def require_role(context: AuthContext, role: UserRole):
    if context.role != role:
        raise HTTPException(status_code=403, detail=f"{role.title()} access required")

    if not context.profile:
        raise HTTPException(
            status_code=403,
            detail=f"{role.title()} profile is incomplete",
        )

    return context.profile


def require_any_role(context: AuthContext, *roles: UserRole):
    if context.role not in roles:
        allowed = " or ".join(role.title() for role in roles)
        raise HTTPException(status_code=403, detail=f"{allowed} access required")

    if not context.profile:
        raise HTTPException(status_code=403, detail="Account profile is incomplete")

    return context.profile
