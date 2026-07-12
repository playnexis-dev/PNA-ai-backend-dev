from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.auth_context import AuthContext
from app.core.supabase import get_supabase_client
from app.profile.schemas import ProfileUpdate


def get_current_profile(context: AuthContext):
    return {
        "user": {
            "id": context.user.id,
            "email": context.user.email,
            "role": context.role,
        },
        "role": context.role,
        "profile": context.profile,
        "needs_profile_completion": not (context.profile or {}).get("phone"),
    }


def update_current_profile(context: AuthContext, payload: ProfileUpdate):
    table = "players" if context.role == "player" else "owners"
    data = payload.model_dump(exclude_unset=True, mode="json")

    if context.role == "player":
        data.pop("company_name", None)
    else:
        data.pop("avatar_url", None)

    data = {key: value for key, value in data.items() if value is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No profile fields to update")

    if "phone" in data and not data["phone"].strip():
        raise HTTPException(status_code=400, detail="Phone number is required")
    if "phone" in data:
        data["phone_verified"] = True

    client = get_supabase_client(context.access_token)
    try:
        if context.profile:
            response = (
                client.table(table)
                .update(data)
                .eq("user_id", context.user.id)
                .execute()
            )
        else:
            insert_payload = {
                "user_id": context.user.id,
                "email": context.user.email,
                "full_name": data.get("full_name") or context.user.email.split("@", 1)[0],
                **data,
            }
            response = client.table(table).insert(insert_payload).execute()
    except APIError as exc:
        detail = exc.message or "Failed to update profile"
        if "Phone number is already used" in detail:
            detail = "Phone number is already used by another profile"
        raise HTTPException(status_code=400, detail=detail) from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to update profile")

    return {
        "role": context.role,
        "profile": response.data[0],
        "needs_profile_completion": not response.data[0].get("phone"),
    }
