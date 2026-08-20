from fastapi import APIRouter, Depends

from app.booking.schemas import BookingCreate, BookingStatusUpdate, PaymentCreate
from app.booking.service import (
    cancel_player_booking,
    create_booking,
    hide_player_booking,
    list_owner_bookings,
    list_player_bookings,
    simulate_payment,
    update_booking_status,
)
from app.core.auth_context import AuthContext, get_current_auth_context, require_verified_email

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.get("/player")
async def player_bookings(
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_player_bookings(context)


@router.get("/owner")
async def owner_bookings(
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_owner_bookings(context)


@router.post("")
async def player_create_booking(
    payload: BookingCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    require_verified_email(context)
    return create_booking(context, payload)


@router.patch("/player/{booking_id}/cancel")
async def player_cancel_booking(
    booking_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return cancel_player_booking(context, booking_id)


@router.delete("/player/{booking_id}")
async def player_delete_booking(
    booking_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return hide_player_booking(context, booking_id)


@router.patch("/{booking_id}/status")
async def owner_update_booking_status(
    booking_id: str,
    payload: BookingStatusUpdate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return update_booking_status(context, booking_id, payload)


@router.post("/{booking_id}/payments/simulate")
async def player_simulate_payment(
    booking_id: str,
    payload: PaymentCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    require_verified_email(context)
    return simulate_payment(context, booking_id, payload)
