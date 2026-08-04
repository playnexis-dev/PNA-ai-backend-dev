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


def get_review_eligibility(context: AuthContext, arena_id: str):
    player = require_role(context, "player")
    admin_client = get_supabase_admin_client()
    bookings = (
        admin_client.table("bookings")
        .select("id, booking_date, created_at")
        .eq("player_id", player["id"])
        .eq("arena_id", arena_id)
        .eq("status", "completed")
        .order("booking_date", desc=True)
        .execute()
        .data
        or []
    )

    if bookings:
        booking_ids = [booking["id"] for booking in bookings]
        reviewed_booking_ids = {
            review["booking_id"]
            for review in (
                admin_client.table("reviews")
                .select("booking_id")
                .eq("player_id", player["id"])
                .in_("booking_id", booking_ids)
                .execute()
                .data
                or []
            )
        }
        eligible_booking = next(
            (booking for booking in bookings if booking["id"] not in reviewed_booking_ids),
            None,
        )
        if eligible_booking:
            return {
                "can_review": True,
                "booking_id": eligible_booking["id"],
                "reason": None,
            }

    offline_review = (
        admin_client.table("reviews")
        .select("id")
        .eq("player_id", player["id"])
        .eq("arena_id", arena_id)
        .is_("booking_id", "null")
        .maybe_single()
        .execute()
    )
    if offline_review and offline_review.data:
        return {
            "can_review": False,
            "booking_id": None,
            "reason": "You have already reviewed this arena.",
        }

    return {
        "can_review": True,
        "booking_id": None,
        "reason": "Visited offline? You can still share your arena experience.",
    }


def create_review(context: AuthContext, payload: ReviewCreate):
    player = require_role(context, "player")
    admin_client = get_supabase_admin_client()
    arena_id = payload.arena_id

    if payload.booking_id:
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
        arena_id = booking["arena_id"]
    else:
        if not arena_id:
            raise HTTPException(status_code=400, detail="Arena is required for an offline review")

        arena_response = (
            admin_client.table("arenas")
            .select("id")
            .eq("id", arena_id)
            .maybe_single()
            .execute()
        )
        if not arena_response or not arena_response.data:
            raise HTTPException(status_code=404, detail="Arena not found")

        existing = (
            admin_client.table("reviews")
            .select("id")
            .eq("player_id", player["id"])
            .eq("arena_id", arena_id)
            .is_("booking_id", "null")
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            raise HTTPException(status_code=400, detail="You have already reviewed this arena")

    try:
        response = admin_client.table("reviews").insert({
            "booking_id": payload.booking_id,
            "player_id": player["id"],
            "arena_id": arena_id,
            "rating": payload.rating,
            "comment": payload.comment,
        }).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    _refresh_arena_rating(arena_id)
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
