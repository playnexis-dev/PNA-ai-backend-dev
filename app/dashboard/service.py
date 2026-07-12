from collections import Counter, defaultdict

from app.core.auth_context import AuthContext, require_role
from app.core.supabase import get_supabase_client


def _client(context: AuthContext):
    return get_supabase_client(context.access_token)


def get_player_dashboard(context: AuthContext):
    player = require_role(context, "player")
    client = _client(context)

    bookings = (
        client.table("bookings")
        .select("*, arenas(*)")
        .eq("player_id", player["id"])
        .order("booking_date", desc=True)
        .execute()
        .data
        or []
    )
    notifications = (
        client.table("notifications")
        .select("*")
        .eq("user_id", context.user.id)
        .eq("role", "player")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data
        or []
    )
    recommended_arenas = (
        get_supabase_client()
        .table("arenas")
        .select("*")
        .eq("is_active", True)
        .eq("status", "active")
        .order("rating", desc=True)
        .limit(6)
        .execute()
        .data
        or []
    )

    total_spent = sum(float(item.get("total_amount") or 0) for item in bookings)
    upcoming = [
        item for item in bookings if item.get("status") in ("pending", "confirmed")
    ]

    return {
        "profile": player,
        "summary": {
            "total_bookings": len(bookings),
            "upcoming_bookings": len(upcoming),
            "completed_bookings": len([item for item in bookings if item.get("status") == "completed"]),
            "total_spent": total_spent,
            "unread_notifications": len([item for item in notifications if not item.get("is_read")]),
        },
        "bookings": bookings,
        "recommended_arenas": recommended_arenas,
        "notifications": notifications,
    }


def get_owner_dashboard(context: AuthContext):
    owner = require_role(context, "owner")
    client = _client(context)

    arenas = (
        client.table("arenas")
        .select("*")
        .eq("owner_id", owner["id"])
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    bookings = (
        client.table("bookings")
        .select("*, arenas(*), players(*)")
        .eq("owner_id", owner["id"])
        .order("booking_date", desc=True)
        .execute()
        .data
        or []
    )
    payments = []
    if bookings:
        booking_ids = [item["id"] for item in bookings]
        payments = (
            client.table("payments")
            .select("*")
            .in_("booking_id", booking_ids)
            .execute()
            .data
            or []
        )

    notifications = (
        client.table("notifications")
        .select("*")
        .eq("user_id", context.user.id)
        .eq("role", "owner")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data
        or []
    )

    revenue = sum(float(item.get("amount") or 0) for item in payments if item.get("status") == "success")
    status_counts = Counter(item.get("status") for item in bookings)
    arena_revenue = defaultdict(float)
    booking_lookup = {item["id"]: item for item in bookings}
    for payment in payments:
        booking = booking_lookup.get(payment.get("booking_id"))
        if booking:
            arena_revenue[booking.get("arena_id")] += float(payment.get("amount") or 0)

    arena_performance = [
        {
            **arena,
            "booking_count": len([item for item in bookings if item.get("arena_id") == arena["id"]]),
            "revenue": arena_revenue.get(arena["id"], 0),
        }
        for arena in arenas
    ]

    return {
        "profile": owner,
        "summary": {
            "total_arenas": len(arenas),
            "active_arenas": len([item for item in arenas if item.get("is_active")]),
            "total_bookings": len(bookings),
            "pending_bookings": status_counts.get("pending", 0),
            "confirmed_bookings": status_counts.get("confirmed", 0),
            "completed_bookings": status_counts.get("completed", 0),
            "total_revenue": revenue,
            "unread_notifications": len([item for item in notifications if not item.get("is_read")]),
        },
        "arenas": arenas,
        "bookings": bookings,
        "payments": payments,
        "arena_performance": arena_performance,
        "notifications": notifications,
    }
