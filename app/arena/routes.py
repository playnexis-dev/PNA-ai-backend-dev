from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app.arena.schemas import (
    ArenaCreate,
    ArenaImageDelete,
    ArenaImagesReorder,
    MaintenanceCancel,
    MaintenanceCreate,
    SlotCopy,
    ArenaUpdate,
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
    get_arena_contact,
    get_public_arena_detail,
    get_owner_arena_detail,
    list_active_arenas,
    list_available_slots,
    list_maintenance_windows,
    list_owner_arenas,
    list_owner_slots,
    list_owner_turfs,
    list_public_turfs,
    remove_arena_image,
    remove_turf_media,
    reorder_arena_images,
    set_arena_active,
    set_arena_booking_enabled,
    set_turf_active,
    update_arena,
    update_slot,
    update_turf,
    upload_arena_image,
    upload_arena_media,
    upload_payment_qr,
    upload_turf_media,
)
from app.core.auth_context import AuthContext, get_current_auth_context

router = APIRouter(prefix="/arenas", tags=["Arenas"])


@router.get("")
async def public_arenas(
    city: str | None = Query(default=None),
    sport: str | None = Query(default=None),
):
    return list_active_arenas(city=city, sport=sport)


@router.get("/owner")
async def owner_arenas(
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_owner_arenas(context)


@router.get("/owner/{arena_id}")
async def owner_arena_detail(
    arena_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_owner_arena_detail(context, arena_id)


@router.post("")
async def owner_create_arena(
    payload: ArenaCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_arena(context, payload)


@router.post("/with-payment-qr")
async def owner_create_arena_with_qr(
    payload: str = Form(...),
    payment_qr: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    try:
        arena_payload = ArenaCreate.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc

    content = await payment_qr.read()
    return create_arena_with_payment_qr(
        context,
        arena_payload,
        payment_qr.filename or "payment-qr.png",
        payment_qr.content_type or "application/octet-stream",
        content,
    )


@router.get("/{arena_id}")
async def arena_detail(arena_id: str):
    return get_public_arena_detail(arena_id)


@router.get("/{arena_id}/contact")
async def authenticated_arena_contact(
    arena_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_arena_contact(context, arena_id)


@router.patch("/{arena_id}")
async def owner_update_arena(
    arena_id: str,
    payload: ArenaUpdate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return update_arena(context, arena_id, payload)


@router.patch("/{arena_id}/active")
async def owner_set_arena_active(
    arena_id: str,
    is_active: bool,
    context: AuthContext = Depends(get_current_auth_context),
):
    return set_arena_active(context, arena_id, is_active)


@router.patch("/{arena_id}/booking-enabled")
async def owner_set_arena_booking_enabled(
    arena_id: str,
    booking_enabled: bool,
    context: AuthContext = Depends(get_current_auth_context),
):
    return set_arena_booking_enabled(context, arena_id, booking_enabled)


@router.delete("/{arena_id}")
async def owner_delete_arena(
    arena_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return delete_arena(context, arena_id)


@router.get("/{arena_id}/slots")
async def arena_available_slots(
    arena_id: str,
    slot_date: date | None = Query(default=None),
    turf_id: str | None = Query(default=None),
):
    return list_available_slots(arena_id, slot_date, turf_id)


@router.get("/{arena_id}/turfs")
async def arena_turfs(arena_id: str):
    return list_public_turfs(arena_id)


@router.get("/{arena_id}/owner-turfs")
async def owner_arena_turfs(
    arena_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_owner_turfs(context, arena_id)


@router.post("/{arena_id}/turfs")
async def owner_create_turf(
    arena_id: str,
    payload: TurfCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_turf(context, arena_id, payload)


@router.patch("/{arena_id}/turfs/{turf_id}")
async def owner_update_turf(
    arena_id: str,
    turf_id: str,
    payload: TurfUpdate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return update_turf(context, arena_id, turf_id, payload)


@router.patch("/{arena_id}/turfs/{turf_id}/active")
async def owner_set_turf_active(
    arena_id: str,
    turf_id: str,
    is_active: bool,
    context: AuthContext = Depends(get_current_auth_context),
):
    return set_turf_active(context, arena_id, turf_id, is_active)


@router.delete("/{arena_id}/turfs/{turf_id}")
async def owner_delete_turf(
    arena_id: str,
    turf_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return delete_turf(context, arena_id, turf_id)


@router.post("/{arena_id}/turfs/{turf_id}/media")
async def owner_upload_turf_media(
    arena_id: str,
    turf_id: str,
    file: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    content = await file.read()
    return upload_turf_media(
        context,
        arena_id,
        turf_id,
        file.filename or "turf-media",
        file.content_type or "application/octet-stream",
        content,
    )


@router.delete("/{arena_id}/turfs/{turf_id}/media")
async def owner_remove_turf_media(
    arena_id: str,
    turf_id: str,
    payload: ArenaImageDelete,
    context: AuthContext = Depends(get_current_auth_context),
):
    if not payload.url:
        raise HTTPException(status_code=400, detail="Media URL is required")
    return remove_turf_media(context, arena_id, turf_id, payload.url)


@router.get("/{arena_id}/maintenance")
async def owner_maintenance_windows(
    arena_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_maintenance_windows(context, arena_id)


@router.post("/{arena_id}/maintenance")
async def owner_create_maintenance_window(
    arena_id: str,
    payload: MaintenanceCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_maintenance_window(context, arena_id, payload)


@router.patch("/{arena_id}/maintenance/{maintenance_id}/cancel")
async def owner_cancel_maintenance_window(
    arena_id: str,
    maintenance_id: str,
    payload: MaintenanceCancel | None = None,
    context: AuthContext = Depends(get_current_auth_context),
):
    return cancel_maintenance_window(context, arena_id, maintenance_id, payload)


@router.get("/{arena_id}/owner-slots")
async def owner_arena_slots(
    arena_id: str,
    slot_date: date | None = Query(default=None),
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_owner_slots(context, arena_id, slot_date)


@router.post("/{arena_id}/images")
async def owner_upload_arena_image(
    arena_id: str,
    file: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    content = await file.read()
    return upload_arena_image(
        context,
        arena_id,
        file.filename or "arena.jpg",
        file.content_type or "application/octet-stream",
        content,
    )


@router.post("/{arena_id}/media")
async def owner_upload_arena_media(
    arena_id: str,
    file: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    content = await file.read()
    return upload_arena_media(
        context,
        arena_id,
        file.filename or "arena-media",
        file.content_type or "application/octet-stream",
        content,
    )


@router.post("/{arena_id}/payment-qr")
async def owner_upload_payment_qr(
    arena_id: str,
    payment_qr: UploadFile = File(...),
    context: AuthContext = Depends(get_current_auth_context),
):
    content = await payment_qr.read()
    return upload_payment_qr(
        context,
        arena_id,
        payment_qr.filename or "payment-qr.png",
        payment_qr.content_type or "application/octet-stream",
        content,
    )


@router.delete("/{arena_id}/images")
async def owner_remove_arena_image(
    arena_id: str,
    payload: ArenaImageDelete,
    context: AuthContext = Depends(get_current_auth_context),
):
    if not payload.url:
        raise HTTPException(status_code=400, detail="Media URL is required")
    return remove_arena_image(context, arena_id, payload.url)


@router.delete("/{arena_id}/media")
async def owner_remove_arena_media(
    arena_id: str,
    payload: ArenaImageDelete,
    context: AuthContext = Depends(get_current_auth_context),
):
    if not payload.url:
        raise HTTPException(status_code=400, detail="Media URL is required")
    return remove_arena_image(context, arena_id, payload.url)


@router.patch("/{arena_id}/images/reorder")
async def owner_reorder_arena_images(
    arena_id: str,
    payload: ArenaImagesReorder,
    context: AuthContext = Depends(get_current_auth_context),
):
    return reorder_arena_images(context, arena_id, payload.images)


@router.patch("/{arena_id}/media/reorder")
async def owner_reorder_arena_media(
    arena_id: str,
    payload: ArenaImagesReorder,
    context: AuthContext = Depends(get_current_auth_context),
):
    return reorder_arena_images(context, arena_id, payload.images)


@router.post("/{arena_id}/slots")
async def owner_create_slot(
    arena_id: str,
    payload: SlotCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_slot(context, arena_id, payload)


@router.post("/{arena_id}/slots/copy")
async def owner_copy_slots(
    arena_id: str,
    payload: SlotCopy,
    context: AuthContext = Depends(get_current_auth_context),
):
    return copy_slots_to_date(context, arena_id, payload)


@router.patch("/{arena_id}/slots/{slot_id}")
async def owner_update_slot(
    arena_id: str,
    slot_id: str,
    payload: SlotUpdate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return update_slot(context, arena_id, slot_id, payload)


@router.delete("/{arena_id}/slots/{slot_id}")
async def owner_delete_slot(
    arena_id: str,
    slot_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return delete_slot(context, arena_id, slot_id)
