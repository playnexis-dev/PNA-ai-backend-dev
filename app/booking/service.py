from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.booking.schemas import BookingCreate, BookingStatusUpdate, PaymentCreate
from app.core.auth_context import AuthContext, require_role
from app.core.supabase import get_supabase_admin_client, get_supabase_client


def _client(context: AuthContext):
    return get_supabase_client(context.access_token)


def _clean_payload(payload):
    return {
        key: value
        for key, value in payload.model_dump(exclude_unset=True, mode="json").items()
        if value is not None
    }


def list_player_bookings(context: AuthContext):
    player = require_role(context, "player")
    response = (
        _client(context)
        .table("bookings")
        .select("*, arenas(*), payments(*)")
        .eq("player_id", player["id"])
        .order("booking_date", desc=True)
        .execute()
    )

    return [
        booking
        for booking in (response.data or [])
        if not (booking.get("metadata") or {}).get("player_hidden")
    ]


def list_owner_bookings(context: AuthContext):
    owner = require_role(context, "owner")
    response = (
        _client(context)
        .table("bookings")
        .select("*, arenas(*), players(*), payments(*)")
        .eq("owner_id", owner["id"])
        .order("booking_date", desc=True)
        .execute()
    )

    return response.data or []


def create_booking(context: AuthContext, payload: BookingCreate):
    player = require_role(context, "player")
    client = _client(context)
    arena = _get_arena(payload.arena_id)
    requested_slot_ids = list(dict.fromkeys(payload.slot_ids or ([payload.slot_id] if payload.slot_id else [])))
    slots = _get_slots(requested_slot_ids) if requested_slot_ids else []
    slot = slots[0] if slots else None

    for item in slots:
        if item["arena_id"] != payload.arena_id:
            raise HTTPException(status_code=400, detail="Slot does not belong to this arena")

        if payload.turf_id and item.get("turf_id") and item.get("turf_id") != payload.turf_id:
            raise HTTPException(status_code=400, detail="Slot does not belong to the selected turf")

        if item.get("status") != "active":
            raise HTTPException(status_code=400, detail="Selected slot is not available")

        if int(item.get("booked_count") or 0) >= int(item.get("capacity") or 1):
            raise HTTPException(status_code=400, detail="Selected slot is already booked")

    if slots:
        booking_dates = {str(item.get("slot_date")) for item in slots}
        if len(booking_dates) > 1:
            raise HTTPException(status_code=400, detail="Selected slots must be on the same date")
        slots = sorted(slots, key=lambda item: str(item.get("start_time")))

    booking_date = payload.booking_date or (slot or {}).get("slot_date")
    start_time = payload.start_time or (slot or {}).get("start_time")
    end_time = payload.end_time or (slots[-1] if slots else {}).get("end_time")

    if not booking_date or not start_time or not end_time:
        raise HTTPException(
            status_code=400,
            detail="Booking date, start time, and end time are required",
        )

    _ensure_future_booking_time(booking_date, start_time)
    turf_id = payload.turf_id or (slot or {}).get("turf_id")
    _ensure_not_in_maintenance(arena["id"], turf_id, booking_date, start_time, end_time)

    total_amount = payload.total_amount
    if total_amount is None:
        if slots:
            total_amount = sum(float(item.get("price") or arena.get("base_price") or 0) for item in slots)
        else:
            total_amount = float(arena.get("base_price") or 0)

    metadata = dict(payload.metadata or {})
    if turf_id:
        metadata["turf_id"] = turf_id
    if slots:
        metadata["selected_slot_ids"] = [item["id"] for item in slots]
        metadata["selected_slots"] = [str(item.get("start_time"))[:5] for item in slots]

    booking_payload = {
        "player_id": player["id"],
        "owner_id": arena["owner_id"],
        "arena_id": arena["id"],
        "turf_id": turf_id,
        "slot_id": slot.get("id") if slot else payload.slot_id,
        "slot_date": str(booking_date),
        "booking_date": str(booking_date),
        "start_time": str(start_time),
        "end_time": str(end_time),
        "sport": payload.sport or arena["sport"],
        "status": "confirmed" if payload.simulate_payment else "pending",
        "payment_status": "paid" if payload.simulate_payment else "pending",
        "total_amount": total_amount,
        "notes": payload.notes,
        "metadata": metadata,
    }

    try:
        response = client.table("bookings").insert(booking_payload).execute()
    except APIError as exc:
        raise _booking_data_error(exc) from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create booking")

    booking = response.data[0]

    for item in slots:
        _increment_slot_booking(item)

    if payload.simulate_payment:
        payment = simulate_payment(
            context,
            booking["id"],
            PaymentCreate(amount=total_amount),
        )
        booking["payments"] = [payment]

    _notify_booking_created(context, booking, arena)

    return booking


def _booking_data_error(exc: APIError):
    detail = " ".join(
        str(part)
        for part in (
            getattr(exc, "message", None),
            getattr(exc, "details", None),
            getattr(exc, "hint", None),
            getattr(exc, "code", None),
        )
        if part
    ) or "Booking request failed"

    lower_detail = detail.lower()
    if "player_id" in lower_detail and "foreign key" in lower_detail:
        detail = "Player profile is not linked correctly. Please log out and log in as player again."
    elif "slot_date" in lower_detail and "null" in lower_detail:
        detail = "Booking date is required."

    return HTTPException(status_code=400, detail=detail)


def update_booking_status(
    context: AuthContext,
    booking_id: str,
    payload: BookingStatusUpdate,
):
    owner = require_role(context, "owner")
    response = (
        _client(context)
        .table("bookings")
        .update({"status": payload.status})
        .eq("id", booking_id)
        .eq("owner_id", owner["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking = response.data[0]
    if payload.status in ("cancelled", "rejected"):
        _release_booking_slot(booking)
    _notify_booking_status_changed(context, booking, payload.status)

    return booking


def cancel_player_booking(context: AuthContext, booking_id: str):
    player = require_role(context, "player")
    client = _client(context)
    admin_client = get_supabase_admin_client()
    existing_response = (
        client.table("bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("player_id", player["id"])
        .maybe_single()
        .execute()
    )

    booking = existing_response.data if existing_response else None
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.get("status") not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail="Only upcoming bookings can be cancelled")

    metadata = booking.get("metadata") or {}
    metadata["cancelled_by"] = "player"
    metadata["refund_status"] = "simulated"

    try:
        response = (
            admin_client.table("bookings")
            .update({
                "status": "cancelled",
                "payment_status": "refunded" if booking.get("payment_status") == "paid" else booking.get("payment_status"),
                "metadata": metadata,
            })
            .eq("id", booking_id)
            .eq("player_id", player["id"])
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found")

    updated = response.data[0]
    _release_booking_slot(updated)
    _notify_booking_cancelled_by_player(context, updated)
    return updated


def hide_player_booking(context: AuthContext, booking_id: str):
    player = require_role(context, "player")
    client = _client(context)
    admin_client = get_supabase_admin_client()
    existing_response = (
        client.table("bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("player_id", player["id"])
        .maybe_single()
        .execute()
    )

    booking = existing_response.data if existing_response else None
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.get("status") in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail="Cancel upcoming bookings before deleting them from your list")

    metadata = booking.get("metadata") or {}
    metadata["player_hidden"] = True

    try:
        response = (
            admin_client.table("bookings")
            .update({"metadata": metadata})
            .eq("id", booking_id)
            .eq("player_id", player["id"])
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found")

    return {"deleted": True}


def simulate_payment(context: AuthContext, booking_id: str, payload: PaymentCreate):
    player = require_role(context, "player")
    user_client = _client(context)
    admin_client = get_supabase_admin_client()
    booking_response = (
        user_client.table("bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("player_id", player["id"])
        .maybe_single()
        .execute()
    )

    if not booking_response or not booking_response.data:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking = booking_response.data
    amount = payload.amount if payload.amount is not None else booking["total_amount"]
    payment_payload = {
        "booking_id": booking_id,
        "player_id": player["id"],
        "amount": amount,
        "status": "success",
        "provider": "simulated",
        "provider_reference": payload.provider_reference or f"sim-{booking_id}",
        "metadata": payload.metadata,
    }

    try:
        response = (
            admin_client.table("payments")
            .upsert(payment_payload, on_conflict="booking_id")
            .execute()
        )
        admin_client.table("bookings").update(
            {"payment_status": "paid", "status": "confirmed"}
        ).eq("id", booking_id).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to record payment")

    return response.data[0]


def _get_arena(arena_id: str):
    response = (
        get_supabase_client()
        .table("arenas")
        .select("*")
        .eq("id", arena_id)
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    return response.data


def _get_slot(slot_id: str):
    response = (
        get_supabase_client()
        .table("arena_slots")
        .select("*")
        .eq("id", slot_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Slot not found")

    return response.data


def _get_slots(slot_ids: list[str]):
    if not slot_ids:
        return []

    response = (
        get_supabase_client()
        .table("arena_slots")
        .select("*")
        .in_("id", slot_ids)
        .execute()
    )

    slots = response.data or []
    if len(slots) != len(slot_ids):
        raise HTTPException(status_code=404, detail="One or more selected slots were not found")

    return slots


def _ensure_future_booking_time(booking_date: date | str, start_time: time | str):
    parsed_date = booking_date
    parsed_time = start_time

    if isinstance(parsed_date, str):
        parsed_date = date.fromisoformat(parsed_date)

    if isinstance(parsed_time, str):
        parsed_time = time.fromisoformat(parsed_time)

    if parsed_date > date.today() + timedelta(days=6):
        raise HTTPException(status_code=400, detail="Bookings are available only for the next 7 days")

    booking_start = datetime.combine(parsed_date, parsed_time)
    if booking_start <= datetime.now():
        raise HTTPException(status_code=400, detail="Cannot book a slot that has already started or passed")


def _ensure_not_in_maintenance(
    arena_id: str,
    turf_id: str | None,
    booking_date: date | str,
    start_time: time | str,
    end_time: time | str,
):
    parsed_date = booking_date if isinstance(booking_date, date) else date.fromisoformat(str(booking_date))
    parsed_start = start_time if isinstance(start_time, time) else time.fromisoformat(str(start_time)[:8])
    parsed_end = end_time if isinstance(end_time, time) else time.fromisoformat(str(end_time)[:8])
    booking_start = datetime.combine(parsed_date, parsed_start)
    booking_end = datetime.combine(parsed_date, parsed_end)
    windows = (
        get_supabase_admin_client()
        .table("arena_maintenance_windows")
        .select("*")
        .eq("arena_id", arena_id)
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    for window in windows:
        window_turf_id = window.get("turf_id")
        if window_turf_id and turf_id and str(window_turf_id) != str(turf_id):
            continue
        if window_turf_id and not turf_id:
            continue
        window_start = _parse_datetime(window.get("start_at"))
        window_end = _parse_datetime(window.get("end_at"))
        if window_start and window_end and booking_start < window_end and booking_end > window_start:
            raise HTTPException(
                status_code=400,
                detail="This arena is under maintenance for the selected time.",
            )


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _increment_slot_booking(slot: dict):
    booked_count = int(slot.get("booked_count") or 0) + 1
    capacity = int(slot.get("capacity") or 1)
    status = "booked" if booked_count >= capacity else slot.get("status", "active")

    get_supabase_admin_client().table("arena_slots").update({
        "booked_count": booked_count,
        "status": status,
    }).eq("id", slot["id"]).execute()


def _release_booking_slot(booking: dict):
    if (booking.get("metadata") or {}).get("slot_released"):
        return

    metadata = booking.get("metadata") or {}
    slot_ids = list(dict.fromkeys(metadata.get("selected_slot_ids") or ([booking.get("slot_id")] if booking.get("slot_id") else [])))
    if not slot_ids:
        return

    admin_client = get_supabase_admin_client()
    slot_response = (
        admin_client.table("arena_slots")
        .select("*")
        .in_("id", slot_ids)
        .execute()
    )
    for slot in (slot_response.data or []):
        booked_count = max(int(slot.get("booked_count") or 0) - 1, 0)
        status = "active" if slot.get("status") == "booked" else slot.get("status", "active")
        admin_client.table("arena_slots").update({
            "booked_count": booked_count,
            "status": status,
        }).eq("id", slot["id"]).execute()

    metadata["slot_released"] = True
    admin_client.table("bookings").update({"metadata": metadata}).eq("id", booking["id"]).execute()


def _notify_booking_created(context: AuthContext, booking: dict, arena: dict):
    admin_client = get_supabase_admin_client()
    owner = (
        admin_client.table("owners")
        .select("user_id")
        .eq("id", arena["owner_id"])
        .maybe_single()
        .execute()
    )
    owner_user_id = (owner.data or {}).get("user_id") if owner else None

    rows = [
        {
            "user_id": context.user.id,
            "role": "player",
            "title": "Booking confirmed",
            "message": f"{arena['name']} - {booking['booking_date']} {str(booking['start_time'])[:5]}",
            "category": "booking",
            "metadata": {"booking_id": booking["id"], "arena_id": arena["id"]},
            "is_read": False,
        }
    ]

    if owner_user_id:
        rows.append({
            "user_id": owner_user_id,
            "role": "owner",
            "title": "New booking received",
            "message": f"{arena['name']} - {booking['booking_date']} {str(booking['start_time'])[:5]}",
            "category": "booking",
            "metadata": {"booking_id": booking["id"], "arena_id": arena["id"]},
            "is_read": False,
        })

    try:
        admin_client.table("notifications").insert(rows).execute()
    except Exception:
        pass


def _notify_booking_cancelled_by_player(context: AuthContext, booking: dict):
    admin_client = get_supabase_admin_client()
    try:
        details = (
            admin_client.table("bookings")
            .select("*, arenas(name), owners(user_id)")
            .eq("id", booking["id"])
            .maybe_single()
            .execute()
        )
    except Exception:
        return
    data = details.data if details else None
    if not data:
        return

    arena_name = (data.get("arenas") or {}).get("name") or "Arena"
    owner_user_id = (data.get("owners") or {}).get("user_id")
    rows = [
        {
            "user_id": context.user.id,
            "role": "player",
            "title": "Booking cancelled",
            "message": f"{arena_name} - {data['booking_date']} {str(data['start_time'])[:5]}",
            "category": "booking",
            "metadata": {"booking_id": booking["id"], "arena_id": data["arena_id"], "status": "cancelled"},
            "is_read": False,
        }
    ]
    if owner_user_id:
        rows.append({
            "user_id": owner_user_id,
            "role": "owner",
            "title": "Booking cancelled by player",
            "message": f"{arena_name} - {data['booking_date']} {str(data['start_time'])[:5]}",
            "category": "booking",
            "metadata": {"booking_id": booking["id"], "arena_id": data["arena_id"], "status": "cancelled"},
            "is_read": False,
        })

    try:
        admin_client.table("notifications").insert(rows).execute()
    except Exception:
        pass


def _notify_booking_status_changed(context: AuthContext, booking: dict, status: str):
    admin_client = get_supabase_admin_client()
    details = (
        admin_client.table("bookings")
        .select("*, players(user_id), arenas(name)")
        .eq("id", booking["id"])
        .maybe_single()
        .execute()
    )
    data = details.data if details else None
    if not data:
        return

    player_user_id = ((data.get("players") or {}).get("user_id"))
    arena_name = (data.get("arenas") or {}).get("name") or "Arena"
    if not player_user_id:
        return

    title_by_status = {
        "confirmed": "Booking confirmed",
        "rejected": "Booking rejected",
        "cancelled": "Booking cancelled",
        "completed": "Booking completed",
        "pending": "Booking pending",
    }

    try:
        admin_client.table("notifications").insert({
            "user_id": player_user_id,
            "role": "player",
            "title": title_by_status.get(status, "Booking updated"),
            "message": f"{arena_name} - {data['booking_date']} {str(data['start_time'])[:5]}",
            "category": "booking",
            "metadata": {"booking_id": booking["id"], "arena_id": data["arena_id"], "status": status},
            "is_read": False,
        }).execute()
    except Exception:
        pass
