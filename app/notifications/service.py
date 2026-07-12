from app.core.auth_context import AuthContext
from app.core.supabase import get_supabase_admin_client


def list_notifications(context: AuthContext):
    response = (
        get_supabase_admin_client()
        .table("notifications")
        .select("*")
        .eq("user_id", context.user.id)
        .eq("role", context.role)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def mark_notification_read(context: AuthContext, notification_id: str):
    response = (
        get_supabase_admin_client()
        .table("notifications")
        .update({"is_read": True})
        .eq("id", notification_id)
        .eq("user_id", context.user.id)
        .execute()
    )

    return response.data[0] if response.data else {"id": notification_id, "is_read": True}


def mark_all_notifications_read(context: AuthContext):
    get_supabase_admin_client().table("notifications").update({"is_read": True}).eq(
        "user_id",
        context.user.id,
    ).eq("role", context.role).execute()

    return {"message": "Notifications marked as read"}


def delete_notification(context: AuthContext, notification_id: str):
    response = (
        get_supabase_admin_client()
        .table("notifications")
        .delete()
        .eq("id", notification_id)
        .eq("user_id", context.user.id)
        .execute()
    )

    return {"deleted": bool(response.data)}
