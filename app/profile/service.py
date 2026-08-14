import logging

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.auth_context import AuthContext
from app.core.supabase import (
    get_supabase_admin_client,
    get_supabase_client,
    is_supabase_admin_configured,
)
from app.profile.schemas import AccountDeleteRequest, ProfileUpdate


logger = logging.getLogger(__name__)


def get_current_profile(context: AuthContext):
    return {
        "user": {
            "id": context.user.id,
            "email": context.user.email,
            "role": context.role,
        },
        "role": context.role,
        "profile": context.profile,
        "needs_profile_completion": context.role != "admin" and not (context.profile or {}).get("phone"),
    }


def update_current_profile(context: AuthContext, payload: ProfileUpdate):
    table = {"player": "players", "owner": "owners", "admin": "admins"}[context.role]
    data = payload.model_dump(exclude_unset=True, mode="json")

    if context.role == "player":
        data.pop("company_name", None)
    elif context.role == "owner":
        data.pop("avatar_url", None)
    else:
        data = {"full_name": data.get("full_name")} if data.get("full_name") else {}

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
        "needs_profile_completion": context.role != "admin" and not response.data[0].get("phone"),
    }


def delete_current_account(context: AuthContext, payload: AccountDeleteRequest):
    if context.role != "player":
        raise HTTPException(status_code=403, detail="Self-service account deletion is currently available to Players only")

    if payload.confirmation_email.casefold() != str(context.user.email or "").casefold():
        raise HTTPException(status_code=400, detail="Enter your signed-in email address to confirm deletion")

    if not is_supabase_admin_configured():
        raise HTTPException(status_code=503, detail="Secure account deletion is not configured on the backend")

    player_id = str((context.profile or {}).get("id") or "")
    if not player_id:
        raise HTTPException(status_code=403, detail="Player profile is incomplete")

    active_bookings = (
        get_supabase_client(context.access_token)
        .table("bookings")
        .select("id")
        .eq("player_id", player_id)
        .in_("status", ["pending", "confirmed"])
        .execute()
        .data
        or []
    )

    # Release inventory cleanly before the profile cascade removes booking rows.
    if active_bookings:
        from app.booking.service import cancel_player_booking

        for booking in active_bookings:
            cancel_player_booking(context, str(booking["id"]))

    admin_client = get_supabase_admin_client()
    user_id = str(context.user.id)
    try:
        # Supabase hard deletion currently fails at the Auth database layer for
        # this project. Soft deletion revokes the identity immediately, after
        # which public application data is removed explicitly below.
        admin_client.auth.admin.delete_user(user_id, should_soft_delete=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Supabase could not delete the account") from exc

    try:
        admin_client.table("players").delete().eq("id", player_id).execute()
        admin_client.table("notifications").delete().eq("user_id", user_id).execute()
        admin_client.table("profile_phone_registry").delete().eq("user_id", user_id).execute()
        admin_client.table("user_roles").delete().eq("user_id", user_id).execute()
    except Exception:
        # Authentication is already revoked, so never report a failed deletion
        # that would leave the frontend holding an unusable session.
        logger.exception("Account %s was disabled but public profile cleanup was incomplete", user_id)

    return {"deleted": True}
