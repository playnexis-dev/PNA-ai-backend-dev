from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.admin.schemas import AdminInviteRequest, AdminStatusUpdate
from app.core.auth_context import AuthContext, require_role
from app.core.supabase import (
    get_supabase_admin_client,
    get_supabase_client,
    is_supabase_admin_configured,
)


def _admin(context: AuthContext) -> dict:
    return require_role(context, "admin")


def _service_admin(context: AuthContext) -> dict:
    profile = _admin(context)
    if not is_supabase_admin_configured():
        raise HTTPException(status_code=503, detail="Admin operations require a Supabase Secret Key")
    return profile


def _audit(
    context: AuthContext,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
):
    get_supabase_client(context.access_token).table("admin_audit_logs").insert({
        "admin_user_id": context.user.id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_data": before,
        "after_data": after,
    }).execute()


def audit_admin_action(
    context: AuthContext,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
):
    _admin(context)
    _audit(context, action, entity_type, entity_id, before, after)


def _auth_users() -> list[Any]:
    result = get_supabase_admin_client().auth.admin.list_users(page=1, per_page=1000)
    if isinstance(result, list):
        return result
    return list(getattr(result, "users", None) or [])


def _auth_user_by_email(email: str):
    normalized = email.strip().casefold()
    return next(
        (user for user in _auth_users() if str(getattr(user, "email", "")).casefold() == normalized),
        None,
    )


def list_admin_users(context: AuthContext):
    _admin(context)
    return (
        get_supabase_client(context.access_token)
        .table("admins")
        .select("*")
        .order("created_at")
        .execute()
        .data
        or []
    )


def invite_admin(context: AuthContext, payload: AdminInviteRequest):
    _service_admin(context)
    client = get_supabase_admin_client()
    email = str(payload.email).strip().lower()
    auth_user = _auth_user_by_email(email)

    if auth_user:
        user_id = str(auth_user.id)
        role_row = (
            client.table("user_roles")
            .select("role")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
            .data
        )
        previous_role = (role_row or {}).get("role")
        if previous_role == "admin":
            raise HTTPException(status_code=409, detail="This account is already an Admin")
        if previous_role not in ("player", "owner"):
            raise HTTPException(status_code=409, detail="Existing account setup is incomplete")
        if not payload.confirm_conversion:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "admin_conversion_confirmation_required",
                    "message": f"This email is currently a {previous_role}. Confirm conversion to Admin.",
                    "previous_role": previous_role,
                },
            )

        client.table("user_roles").upsert(
            {"user_id": user_id, "role": "admin"}, on_conflict="user_id"
        ).execute()
        row = {
            "user_id": user_id,
            "email": email,
            "full_name": payload.full_name,
            "status": "active",
            "invited_by_user_id": context.user.id,
            "previous_role": previous_role,
        }
        admin_profile = client.table("admins").upsert(row, on_conflict="user_id").execute().data[0]
        client.auth.admin.update_user_by_id(user_id, {"ban_duration": "none"})
        _audit(context, "admin.converted", "admin", user_id, {"role": previous_role}, admin_profile)
        return {"admin": admin_profile, "conversion": True, "invitation_sent": False}

    redirect_to = f"{settings.FRONTEND_URL.rstrip('/')}/auth/admin-invite/accept"
    invited = client.auth.admin.invite_user_by_email(
        email,
        {"redirect_to": redirect_to, "data": {"full_name": payload.full_name or ""}},
    )
    invited_user = getattr(invited, "user", None)
    if not invited_user:
        raise HTTPException(status_code=500, detail="Supabase did not return the invited user")
    user_id = str(invited_user.id)
    client.table("user_roles").upsert(
        {"user_id": user_id, "role": "admin"}, on_conflict="user_id"
    ).execute()
    row = {
        "user_id": user_id,
        "email": email,
        "full_name": payload.full_name,
        "status": "invited",
        "invited_by_user_id": context.user.id,
    }
    admin_profile = client.table("admins").upsert(row, on_conflict="user_id").execute().data[0]
    _audit(context, "admin.invited", "admin", user_id, None, admin_profile)
    return {"admin": admin_profile, "conversion": False, "invitation_sent": True}


def update_admin_status(context: AuthContext, user_id: str, payload: AdminStatusUpdate):
    _service_admin(context)
    client = get_supabase_admin_client()
    existing = (
        client.table("admins").select("*").eq("user_id", user_id).maybe_single().execute().data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Admin not found")
    if payload.status == "disabled" and user_id == str(context.user.id):
        raise HTTPException(status_code=400, detail="You cannot disable your own Admin account")
    if payload.status == "disabled":
        active = client.table("admins").select("user_id").eq("status", "active").execute().data or []
        if len(active) <= 1:
            raise HTTPException(status_code=409, detail="The final active Admin cannot be disabled")

    updated = (
        client.table("admins")
        .update({"status": payload.status})
        .eq("user_id", user_id)
        .execute()
        .data
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Admin not found")
    client.auth.admin.update_user_by_id(
        user_id,
        {"ban_duration": "none" if payload.status == "active" else "876000h"},
    )
    _audit(context, f"admin.{payload.status}", "admin", user_id, existing, updated[0])
    return updated[0]


def accept_admin_invite(access_token: str, password: str, full_name: str | None):
    if not is_supabase_admin_configured():
        raise HTTPException(status_code=503, detail="Admin operations require a Supabase Secret Key")
    client = get_supabase_admin_client()
    response = client.auth.get_user(access_token)
    user = getattr(response, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Admin invitation is invalid or expired")
    profile = client.table("admins").select("*").eq("user_id", user.id).maybe_single().execute().data
    role = client.table("user_roles").select("role").eq("user_id", user.id).maybe_single().execute().data
    if not profile or (role or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="This invitation is not for an Admin account")
    if profile.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="Admin account is disabled")

    client.auth.admin.update_user_by_id(str(user.id), {"password": password, "ban_duration": "none"})
    changes: dict[str, Any] = {"status": "active"}
    if full_name:
        changes["full_name"] = full_name.strip()
    updated = client.table("admins").update(changes).eq("user_id", user.id).execute().data[0]
    client.table("admin_audit_logs").insert({
        "admin_user_id": user.id,
        "action": "admin.invite_accepted",
        "entity_type": "admin",
        "entity_id": str(user.id),
        "before_data": profile,
        "after_data": updated,
    }).execute()
    return {"message": "Admin invitation accepted", "admin": updated}


def list_owners_for_admin(context: AuthContext):
    _admin(context)
    return get_supabase_client(context.access_token).table("owners").select("id,user_id,email,full_name,company_name").order("full_name").execute().data or []


def list_all_arenas(context: AuthContext):
    _admin(context)
    client = get_supabase_client(context.access_token)
    arenas = client.table("arenas").select("*, arena_slots(*), turfs(*)").order("created_at", desc=True).execute().data or []
    owner_ids = list({item.get("owner_id") for item in arenas if item.get("owner_id")})
    owners = client.table("owners").select("id,user_id,email,full_name,company_name").in_("id", owner_ids).execute().data if owner_ids else []
    owner_map = {item["id"]: item for item in (owners or [])}
    for arena in arenas:
        arena["owner"] = owner_map.get(arena.get("owner_id"))
    return arenas


def get_arena_for_admin(context: AuthContext, arena_id: str):
    _admin(context)
    arena = get_supabase_client(context.access_token).table("arenas").select("*").eq("id", arena_id).maybe_single().execute().data
    if not arena:
        raise HTTPException(status_code=404, detail="Arena not found")
    return arena


def owner_scoped_context(context: AuthContext, arena_id: str) -> AuthContext:
    arena = get_arena_for_admin(context, arena_id)
    owner = get_supabase_client(context.access_token).table("owners").select("*").eq("id", arena["owner_id"]).maybe_single().execute().data
    if not owner:
        raise HTTPException(status_code=409, detail="Arena owner profile is missing")
    return AuthContext(
        access_token=context.access_token,
        user=context.user,
        role="owner",
        profile=owner,
    )


def owner_scoped_context_for_owner(context: AuthContext, owner_id: str) -> AuthContext:
    _admin(context)
    owner = get_supabase_client(context.access_token).table("owners").select("*").eq("id", owner_id).maybe_single().execute().data
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    return AuthContext(context.access_token, context.user, "owner", owner)


def set_arena_management(context: AuthContext, arena_id: str, management_mode: str):
    before = get_arena_for_admin(context, arena_id)
    updated = (
        get_supabase_client(context.access_token).table("arenas")
        .update({"management_mode": management_mode})
        .eq("id", arena_id)
        .execute().data
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Arena not found")
    _audit(context, "arena.management_changed", "arena", arena_id, before, updated[0])
    return updated[0]


def list_all_bookings(context: AuthContext):
    _admin(context)
    return get_supabase_client(context.access_token).table("bookings").select("*, arenas(*), players(*), payments(*)").order("booking_date", desc=True).execute().data or []


def admin_dashboard(context: AuthContext):
    admin = _admin(context)
    arenas = list_all_arenas(context)
    bookings = list_all_bookings(context)
    statuses = Counter(item.get("status") for item in bookings)
    return {
        "profile": admin,
        "summary": {
            "total_arenas": len(arenas),
            "active_arenas": sum(bool(item.get("is_active")) for item in arenas),
            "total_bookings": len(bookings),
            "pending_bookings": statuses.get("pending", 0),
            "confirmed_bookings": statuses.get("confirmed", 0),
            "completed_bookings": statuses.get("completed", 0),
            "total_revenue": sum(float(item.get("total_amount") or 0) for item in bookings if item.get("payment_status") == "paid"),
            "unread_notifications": 0,
        },
        "arenas": arenas,
        "bookings": bookings,
        "payments": [],
        "arena_performance": [],
        "notifications": [],
    }
