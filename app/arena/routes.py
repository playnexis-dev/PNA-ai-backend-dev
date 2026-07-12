from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.arena.schemas import (
    ArenaCreate,
    ArenaImageDelete,
    ArenaImagesReorder,
    SlotCopy,
    ArenaUpdate,
    SlotCreate,
    SlotUpdate,
)
from app.arena.service import (
    copy_slots_to_date,
    create_arena,
    create_slot,
    delete_slot,
    get_arena_detail,
    list_active_arenas,
    list_available_slots,
    list_owner_arenas,
    list_owner_slots,
    remove_arena_image,
    reorder_arena_images,
    set_arena_active,
    update_arena,
    update_slot,
    upload_arena_image,
    upload_arena_media,
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


@router.post("")
async def owner_create_arena(
    payload: ArenaCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_arena(context, payload)


@router.get("/{arena_id}")
async def arena_detail(arena_id: str):
    return get_arena_detail(arena_id)


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


@router.get("/{arena_id}/slots")
async def arena_available_slots(
    arena_id: str,
    slot_date: date | None = Query(default=None),
):
    return list_available_slots(arena_id, slot_date)


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
