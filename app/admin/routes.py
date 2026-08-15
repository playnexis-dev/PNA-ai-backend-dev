from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app.admin.schemas import (
    AdminArenaCreateRequest,
    AdminInviteAcceptRequest,
    AdminInviteRequest,
    AdminStatusUpdate,
    ArenaManagementUpdate,
)
from app.admin.service import (
    accept_admin_invite,
    admin_dashboard,
    audit_admin_action,
    get_arena_for_admin,
    invite_admin,
    list_admin_users,
    list_all_arenas,
    list_all_bookings,
    list_owners_for_admin,
    owner_scoped_context,
    owner_scoped_context_for_owner,
    set_arena_management,
    update_admin_status,
)
from app.arena.schemas import (
    ArenaCreate,
    ArenaImageDelete,
    ArenaImagesReorder,
    ArenaUpdate,
    MaintenanceCancel,
    MaintenanceCreate,
    RecurringSlotStatusUpdate,
    RecurringSlotStatusesUpdate,
    SlotCopy,
    SlotCreate,
    SlotUpdate,
    TurfCreate,
    TurfUpdate,
)
from app.arena.service import (
    cancel_maintenance_window,
    copy_slots_to_date,
    create_arena,
    create_arena_with_payment_qr,
    create_maintenance_window,
    create_slot,
    create_turf,
    delete_arena,
    delete_slot,
    delete_turf,
    get_owner_arena_detail,
    list_owner_slots,
    remove_arena_image,
    remove_turf_media,
    reorder_arena_images,
    set_arena_active,
    set_arena_booking_enabled,
    set_recurring_slot_status,
    set_recurring_slot_statuses,
    set_turf_active,
    update_arena,
    update_slot,
    update_turf,
    upload_arena_media,
    upload_payment_qr,
    upload_turf_media,
)
from app.booking.schemas import BookingStatusUpdate
from app.booking.service import update_booking_status
from app.core.auth_context import AuthContext, get_current_auth_context


router = APIRouter(prefix="/admin", tags=["Admin"])
public_router = APIRouter(prefix="/auth", tags=["Authentication"])


def _record(context: AuthContext, action: str, entity: str, entity_id: str, result):
    audit_admin_action(context, action, entity, entity_id, after=result if isinstance(result, dict) else None)
    return result


@public_router.post("/admin-invite/accept")
async def admin_invite_accept(payload: AdminInviteAcceptRequest):
    return accept_admin_invite(payload.access_token, payload.password, payload.full_name)


@router.get("/users")
async def admin_users(context: AuthContext = Depends(get_current_auth_context)):
    return list_admin_users(context)


@router.post("/users/invite")
async def admin_user_invite(payload: AdminInviteRequest, context: AuthContext = Depends(get_current_auth_context)):
    return invite_admin(context, payload)


@router.patch("/users/{user_id}/status")
async def admin_user_status(user_id: str, payload: AdminStatusUpdate, context: AuthContext = Depends(get_current_auth_context)):
    return update_admin_status(context, user_id, payload)


@router.get("/owners")
async def admin_owners(context: AuthContext = Depends(get_current_auth_context)):
    return list_owners_for_admin(context)


@router.get("/dashboard")
async def dashboard(context: AuthContext = Depends(get_current_auth_context)):
    return admin_dashboard(context)


@router.get("/bookings")
async def bookings(context: AuthContext = Depends(get_current_auth_context)):
    return list_all_bookings(context)


@router.patch("/bookings/{booking_id}/status")
async def booking_status(booking_id: str, payload: BookingStatusUpdate, context: AuthContext = Depends(get_current_auth_context)):
    booking = next((item for item in list_all_bookings(context) if str(item.get("id")) == booking_id), None)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    scoped = owner_scoped_context(context, str(booking["arena_id"]))
    result = update_booking_status(scoped, booking_id, payload)
    return _record(context, "booking.status_changed", "booking", booking_id, result)


@router.get("/arenas")
async def arenas(
    owner_id: str | None = Query(default=None),
    city: str | None = Query(default=None),
    status: str | None = Query(default=None),
    management_mode: str | None = Query(default=None),
    context: AuthContext = Depends(get_current_auth_context),
):
    rows = list_all_arenas(context)
    if owner_id:
        rows = [row for row in rows if str(row.get("owner_id")) == owner_id]
    if city:
        rows = [row for row in rows if str(row.get("city", "")).casefold() == city.casefold()]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if management_mode:
        rows = [row for row in rows if row.get("management_mode", "owner") == management_mode]
    return rows


@router.post("/arenas")
async def arena_create(payload: AdminArenaCreateRequest, context: AuthContext = Depends(get_current_auth_context)):
    scoped = owner_scoped_context_for_owner(context, payload.owner_id)
    result = create_arena(scoped, payload.arena)
    if payload.management_mode == "admin":
        result = set_arena_management(context, str(result["id"]), "admin")
    return _record(context, "arena.created", "arena", str(result["id"]), result)


@router.post("/arenas/with-payment-qr")
async def arena_create_with_qr(
    owner_id: str = Form(...),
    payload: str = Form(...),
    payment_qr: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    try:
        arena_payload = ArenaCreate.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    scoped = owner_scoped_context_for_owner(context, owner_id)
    result = create_arena_with_payment_qr(
        scoped,
        arena_payload,
        payment_qr.filename or "payment-qr.png",
        payment_qr.content_type or "application/octet-stream",
        await payment_qr.read(),
    )
    return _record(context, "arena.created", "arena", str(result["id"]), result)


@router.get("/arenas/{arena_id}")
async def arena_detail(arena_id: str, context: AuthContext = Depends(get_current_auth_context)):
    arena = get_arena_for_admin(context, arena_id)
    scoped = owner_scoped_context(context, arena_id)
    detail = get_owner_arena_detail(scoped, arena_id)
    detail["arena"]["owner"] = next(
        (owner for owner in list_owners_for_admin(context) if str(owner.get("id")) == str(arena.get("owner_id"))),
        None,
    )
    return detail


@router.patch("/arenas/{arena_id}")
async def arena_update(arena_id: str, payload: ArenaUpdate, context: AuthContext = Depends(get_current_auth_context)):
    before = get_arena_for_admin(context, arena_id)
    result = update_arena(owner_scoped_context(context, arena_id), arena_id, payload)
    audit_admin_action(context, "arena.updated", "arena", arena_id, before, result)
    return result


@router.patch("/arenas/{arena_id}/management")
async def arena_management(arena_id: str, payload: ArenaManagementUpdate, context: AuthContext = Depends(get_current_auth_context)):
    return set_arena_management(context, arena_id, payload.management_mode, payload.owner_id)


@router.patch("/arenas/{arena_id}/active")
async def arena_active(arena_id: str, is_active: bool, context: AuthContext = Depends(get_current_auth_context)):
    result = set_arena_active(owner_scoped_context(context, arena_id), arena_id, is_active)
    return _record(context, "arena.activation_changed", "arena", arena_id, result)


@router.patch("/arenas/{arena_id}/booking-enabled")
async def arena_booking_enabled(arena_id: str, booking_enabled: bool, context: AuthContext = Depends(get_current_auth_context)):
    result = set_arena_booking_enabled(owner_scoped_context(context, arena_id), arena_id, booking_enabled)
    return _record(context, "arena.booking_changed", "arena", arena_id, result)


@router.delete("/arenas/{arena_id}")
async def arena_delete(arena_id: str, context: AuthContext = Depends(get_current_auth_context)):
    result = delete_arena(owner_scoped_context(context, arena_id), arena_id)
    return _record(context, "arena.deleted", "arena", arena_id, result)


@router.post("/arenas/{arena_id}/payment-qr")
async def arena_payment_qr(arena_id: str, payment_qr: UploadFile = File(...), context: AuthContext = Depends(get_current_auth_context)):
    result = upload_payment_qr(owner_scoped_context(context, arena_id), arena_id, payment_qr.filename or "payment-qr.png", payment_qr.content_type or "application/octet-stream", await payment_qr.read())
    return _record(context, "arena.payment_qr_uploaded", "arena", arena_id, result)


@router.post("/arenas/{arena_id}/media")
async def arena_media(arena_id: str, file: UploadFile = File(...), context: AuthContext = Depends(get_current_auth_context)):
    result = upload_arena_media(owner_scoped_context(context, arena_id), arena_id, file.filename or "arena-media", file.content_type or "application/octet-stream", await file.read())
    return _record(context, "arena.media_uploaded", "arena", arena_id, result)


@router.delete("/arenas/{arena_id}/media")
async def arena_media_remove(arena_id: str, payload: ArenaImageDelete, context: AuthContext = Depends(get_current_auth_context)):
    result = remove_arena_image(owner_scoped_context(context, arena_id), arena_id, payload.url)
    return _record(context, "arena.media_removed", "arena", arena_id, result)


@router.patch("/arenas/{arena_id}/media/reorder")
async def arena_media_reorder(arena_id: str, payload: ArenaImagesReorder, context: AuthContext = Depends(get_current_auth_context)):
    result = reorder_arena_images(owner_scoped_context(context, arena_id), arena_id, payload.images)
    return _record(context, "arena.media_reordered", "arena", arena_id, result)


@router.post("/arenas/{arena_id}/turfs")
async def turf_create(arena_id: str, payload: TurfCreate, context: AuthContext = Depends(get_current_auth_context)):
    result = create_turf(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "turf.created", "turf", str(result["id"]), result)


@router.patch("/arenas/{arena_id}/turfs/{turf_id}")
async def turf_update(arena_id: str, turf_id: str, payload: TurfUpdate, context: AuthContext = Depends(get_current_auth_context)):
    result = update_turf(owner_scoped_context(context, arena_id), arena_id, turf_id, payload)
    return _record(context, "turf.updated", "turf", turf_id, result)


@router.patch("/arenas/{arena_id}/turfs/{turf_id}/active")
async def turf_active(arena_id: str, turf_id: str, is_active: bool, context: AuthContext = Depends(get_current_auth_context)):
    result = set_turf_active(owner_scoped_context(context, arena_id), arena_id, turf_id, is_active)
    return _record(context, "turf.activation_changed", "turf", turf_id, result)


@router.delete("/arenas/{arena_id}/turfs/{turf_id}")
async def turf_delete(arena_id: str, turf_id: str, context: AuthContext = Depends(get_current_auth_context)):
    result = delete_turf(owner_scoped_context(context, arena_id), arena_id, turf_id)
    return _record(context, "turf.deleted", "turf", turf_id, result)


@router.post("/arenas/{arena_id}/turfs/{turf_id}/media")
async def turf_media(arena_id: str, turf_id: str, file: UploadFile = File(...), context: AuthContext = Depends(get_current_auth_context)):
    result = upload_turf_media(owner_scoped_context(context, arena_id), arena_id, turf_id, file.filename or "turf-media", file.content_type or "application/octet-stream", await file.read())
    return _record(context, "turf.media_uploaded", "turf", turf_id, result)


@router.delete("/arenas/{arena_id}/turfs/{turf_id}/media")
async def turf_media_remove(arena_id: str, turf_id: str, payload: ArenaImageDelete, context: AuthContext = Depends(get_current_auth_context)):
    result = remove_turf_media(owner_scoped_context(context, arena_id), arena_id, turf_id, payload.url)
    return _record(context, "turf.media_removed", "turf", turf_id, result)


@router.post("/arenas/{arena_id}/maintenance")
async def maintenance_create(arena_id: str, payload: MaintenanceCreate, context: AuthContext = Depends(get_current_auth_context)):
    result = create_maintenance_window(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "maintenance.created", "maintenance", str(result["id"]), result)


@router.patch("/arenas/{arena_id}/maintenance/{maintenance_id}/cancel")
async def maintenance_cancel(arena_id: str, maintenance_id: str, payload: MaintenanceCancel | None = None, context: AuthContext = Depends(get_current_auth_context)):
    result = cancel_maintenance_window(owner_scoped_context(context, arena_id), arena_id, maintenance_id, payload)
    return _record(context, "maintenance.cancelled", "maintenance", maintenance_id, result)


@router.get("/arenas/{arena_id}/owner-slots")
async def slots(arena_id: str, slot_date: date | None = Query(default=None), turf_id: str | None = Query(default=None), context: AuthContext = Depends(get_current_auth_context)):
    return list_owner_slots(owner_scoped_context(context, arena_id), arena_id, slot_date, turf_id)


@router.post("/arenas/{arena_id}/slots")
async def slot_create(arena_id: str, payload: SlotCreate, context: AuthContext = Depends(get_current_auth_context)):
    result = create_slot(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "slot.created", "slot", str(result["id"]), result)


@router.post("/arenas/{arena_id}/slots/copy")
async def slot_copy(arena_id: str, payload: SlotCopy, context: AuthContext = Depends(get_current_auth_context)):
    result = copy_slots_to_date(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "slots.copied", "arena", arena_id, {"count": len(result)})


@router.put("/arenas/{arena_id}/slots/recurring-statuses")
async def recurring_slots(arena_id: str, payload: RecurringSlotStatusesUpdate, context: AuthContext = Depends(get_current_auth_context)):
    result = set_recurring_slot_statuses(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "slots.recurring_updated", "arena", arena_id, {"count": len(result)})


@router.patch("/arenas/{arena_id}/slots/recurring-status")
async def recurring_slot(arena_id: str, payload: RecurringSlotStatusUpdate, context: AuthContext = Depends(get_current_auth_context)):
    result = set_recurring_slot_status(owner_scoped_context(context, arena_id), arena_id, payload)
    return _record(context, "slots.recurring_updated", "arena", arena_id, {"count": len(result)})


@router.patch("/arenas/{arena_id}/slots/{slot_id}")
async def slot_update(arena_id: str, slot_id: str, payload: SlotUpdate, context: AuthContext = Depends(get_current_auth_context)):
    result = update_slot(owner_scoped_context(context, arena_id), arena_id, slot_id, payload)
    return _record(context, "slot.updated", "slot", slot_id, result)


@router.delete("/arenas/{arena_id}/slots/{slot_id}")
async def slot_delete(arena_id: str, slot_id: str, context: AuthContext = Depends(get_current_auth_context)):
    result = delete_slot(owner_scoped_context(context, arena_id), arena_id, slot_id)
    return _record(context, "slot.deleted", "slot", slot_id, result)
