from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.auth_context import AuthContext, require_role
from app.core.supabase import get_supabase_admin_client
from app.reviews.schemas import ReviewCreate


def list_arena_reviews(arena_id: str):
    response = (
        get_supabase_admin_client()
        .table("reviews")
        .select("*, players(full_name, avatar_url)")
        .eq("arena_id", arena_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def create_review(context: AuthContext, payload: ReviewCreate):
    player = require_role(context, "player")
    admin_client = get_supabase_admin_client()
    booking_response = (
        admin_client.table("bookings")
        .select("*")
        .eq("id", payload.booking_id)
        .eq("player_id", player["id"])
        .maybe_single()
        .execute()
    )

    if not booking_response or not booking_response.data:
        raise HTTPException(status_code=404, detail="Completed booking not found")

    booking = booking_response.data
    if booking.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Review is allowed only after a completed booking")

    existing = (
        admin_client.table("reviews")
        .select("id")
        .eq("booking_id", payload.booking_id)
        .eq("player_id", player["id"])
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        raise HTTPException(status_code=400, detail="Review already submitted for this booking")

    try:
        response = admin_client.table("reviews").insert({
            "booking_id": payload.booking_id,
            "player_id": player["id"],
            "arena_id": booking["arena_id"],
            "rating": payload.rating,
            "comment": payload.comment,
        }).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    _refresh_arena_rating(booking["arena_id"])
    return response.data[0]


def _refresh_arena_rating(arena_id: str):
    admin_client = get_supabase_admin_client()
    reviews = (
        admin_client.table("reviews")
        .select("rating")
        .eq("arena_id", arena_id)
        .execute()
        .data
        or []
    )
    if not reviews:
        return

    rating = round(sum(int(row["rating"]) for row in reviews) / len(reviews), 2)
    admin_client.table("arenas").update({
        "rating": rating,
        "review_count": len(reviews),
    }).eq("id", arena_id).execute()
