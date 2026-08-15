from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.arena.schemas import (
    ArenaContactEventCreate,
    ArenaCreate,
    ArenaUpdate,
    MaintenanceCancel,
    MaintenanceCreate,
    RecurringSlotStatusChange,
    RecurringSlotStatusUpdate,
    RecurringSlotStatusesUpdate,
    SlotCopy,
    SlotCreate,
    SlotUpdate,
    TurfCreate,
    TurfUpdate,
)
from app.arena.proximity import rank_arenas_by_location
from app.core.auth_context import AuthContext, require_role
from app.core.config import settings
from app.core.supabase import get_supabase_admin_client, get_supabase_client


ARENA_DETAIL_METADATA_FIELDS = (
    "synopsis",
    "contact_country_code",
    "contact_number",
    "contact_email",
    "website",
    "instagram",
    "facebook",
    "cancellation_policy",
    "booking_advance_percent",
)

MEDIA_CACHE_CONTROL_SECONDS = "31536000"


def _client(context: AuthContext):
    return get_supabase_client(context.access_token)


def _storage_upload_error(message: str, exc: Exception) -> HTTPException:
    detail = str(exc)
    if "bucket" in detail.lower() and "not" in detail.lower():
        return HTTPException(
            status_code=400,
            detail=(
                f"{message}: storage bucket '{settings.ARENA_MEDIA_BUCKET}' was not found. "
                "Create it in Supabase Storage or update ARENA_MEDIA_BUCKET."
            ),
        )
    return HTTPException(status_code=400, detail=f"{message}: {detail}")


def _clean_payload(payload):
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(exclude_unset=True, mode="json")
    else:
        data = dict(payload)

    return {key: value for key, value in data.items() if value is not None}


def _move_arena_details_to_metadata(data: dict, existing_metadata: dict | None = None):
    metadata = dict(existing_metadata or {})
    metadata.update(data.pop("metadata", {}) or {})
    for field in ARENA_DETAIL_METADATA_FIELDS:
        if field in data:
            metadata[field] = data.pop(field)
    data["metadata"] = metadata
    return data


TURF_METADATA_FIELDS = (
    "sports",
    "shape",
    "size_unit",
    "area",
    "dimension_length",
    "dimension_width",
    "peak_surcharge",
    "discount_amount",
    "slot_window_minutes",
    "peak_days",
    "discount_days",
    "open_time",
    "close_time",
    "used_for_more_sports",
)


def _move_turf_details_to_metadata(data: dict, existing_metadata: dict | None = None):
    metadata = dict(existing_metadata or {})
    metadata.update(data.pop("metadata", {}) or {})
    for field in TURF_METADATA_FIELDS:
        if field in data:
            metadata[field] = data.pop(field)
    if metadata.get("sports"):
        metadata["sports"] = _normalize_turf_sports(metadata["sports"])
        if metadata["sports"]:
            data["sport"] = metadata["sports"][0]
    elif data.get("sport") and not _is_generic_sport(data["sport"]):
        metadata["sports"] = [data["sport"]]
    data["metadata"] = metadata
    return data


def _unique_strings(values):
    seen = set()
    unique = []
    for value in values or []:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return unique


def _is_generic_sport(value) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "").replace(" ", "")
    return normalized == "multisport"


def _normalize_turf_sports(values):
    return [value for value in _unique_strings(values) if not _is_generic_sport(value)]


def _sanitize_public_arena(arena: dict):
    public_arena = dict(arena)
    public_arena.pop("management_mode", None)
    metadata = dict(public_arena.get("metadata") or {})
    contact_number = "".join(
        character
        for character in str(metadata.pop("contact_number", ""))
        if character.isdigit()
    )
    metadata["contact_number_masked"] = (
        f"{contact_number[:4]}{'*' * max(len(contact_number) - 4, 0)}"
        if contact_number
        else ""
    )
    public_arena["metadata"] = metadata
    return public_arena


def list_active_arenas(
    city: str | None = None,
    sport: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 20,
):
    client = get_supabase_client()
    query = (
        client.table("arenas")
        .select("*, arena_slots(*), turfs(*)")
        .eq("is_active", True)
        .eq("status", "active")
    )

    arenas = query.execute().data or []
    if sport:
        sport_key = sport.strip().casefold()
        arenas = [arena for arena in arenas if _arena_supports_sport(arena, sport_key)]

    ranked = rank_arenas_by_location(
        arenas,
        city=city,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )
    return [_sanitize_public_arena(arena) for arena in ranked]


def _arena_supports_sport(arena: dict, sport_key: str) -> bool:
    if not sport_key:
        return True
    if sport_key in str(arena.get("sport") or "").casefold():
        return True
    for turf in arena.get("turfs") or []:
        sports = (turf.get("metadata") or {}).get("sports") or [turf.get("sport")]
        if any(sport_key == str(item or "").strip().casefold() for item in sports):
            return True
    return False


def get_arena_detail(arena_id: str):
    client = get_supabase_client()
    response = (
        client.table("arenas")
        .select("*, arena_slots(*), turfs(*), reviews(*, players(full_name, avatar_url))")
        .eq("id", arena_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    return response.data


def list_owner_arenas(context: AuthContext):
    owner = require_role(context, "owner")
    response = (
        _client(context)
        .table("arenas")
        .select("*, arena_slots(*), turfs(*)")
        .eq("owner_id", owner["id"])
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_owner_arena_detail(context: AuthContext, arena_id: str):
    owner = require_role(context, "owner")
    _ensure_rolling_week_slots(arena_id)
    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    turfs = list_owner_turfs(context, arena_id)
    maintenance = list_maintenance_windows(context, arena_id)
    slots = list_owner_slots(context, arena_id)
    active_slots = [slot for slot in slots if slot.get("status") == "active"]
    booked_slots = [slot for slot in slots if int(slot.get("booked_count") or 0) > 0]
    return {
        "arena": arena,
        "turfs": turfs,
        "maintenance_windows": maintenance,
        "qr_target_url": _arena_public_url(arena_id),
        "slots_summary": {
            "total": len(slots),
            "active": len(active_slots),
            "booked": len(booked_slots),
        },
    }


def list_owner_slots(
    context: AuthContext,
    arena_id: str,
    slot_date: date | None = None,
    turf_id: str | None = None,
):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    _ensure_full_day_slots_for_turfs(arena_id, turf_id=turf_id)
    if not slot_date or date.today() <= slot_date <= date.today() + timedelta(days=6):
        _ensure_rolling_week_slots(arena_id)

    query = (
        _client(context)
        .table("arena_slots")
        .select("*, turfs(*)")
        .eq("arena_id", arena_id)
        .order("slot_date")
        .order("start_time")
    )

    if slot_date:
        query = query.eq("slot_date", slot_date.isoformat())
    if turf_id:
        query = query.eq("turf_id", turf_id)

    return query.execute().data or []


def create_arena(context: AuthContext, payload: ArenaCreate):
    owner = require_role(context, "owner")
    data = _move_arena_details_to_metadata(_clean_payload(payload))
    data["owner_id"] = owner["id"]
    data["status"] = "active"
    data["is_active"] = True
    data["booking_enabled"] = True
    data["price_unit"] = "slot"

    try:
        response = _client(context).table("arenas").insert(data).execute()
    except APIError as exc:
        raise _arena_data_error(exc) from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create arena")

    arena = response.data[0]
    return arena


def update_arena(context: AuthContext, arena_id: str, payload: ArenaUpdate):
    owner = require_role(context, "owner")
    data = _clean_payload(payload)
    if "base_price" in data or "price_unit" in data:
        data["price_unit"] = "slot"

    if not data:
        raise HTTPException(status_code=400, detail="No arena fields to update")

    existing = (
        _client(context)
        .table("arenas")
        .select("id, images, metadata")
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .maybe_single()
        .execute()
    )

    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    data = _move_arena_details_to_metadata(data, existing.data.get("metadata") or {})

    try:
        response = (
            _client(context)
            .table("arenas")
            .update(data)
            .eq("id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )
    except APIError as exc:
        raise _arena_data_error(exc) from exc

    return response.data[0] if response.data else None


def _arena_data_error(exc: APIError):
    detail = " ".join(
        str(part)
        for part in (
            getattr(exc, "message", None),
            getattr(exc, "details", None),
            getattr(exc, "hint", None),
            getattr(exc, "code", None),
        )
        if part
    ) or "Arena request failed"

    lower_detail = detail.lower()
    if "foreign key" in lower_detail and "owner_id" in lower_detail:
        detail = "Owner profile is not linked correctly. Please log out and log in as owner again."

    return HTTPException(status_code=400, detail=detail)


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 75 * 1024 * 1024


def create_arena_with_payment_qr(
    context: AuthContext,
    payload: ArenaCreate,
    filename: str,
    content_type: str,
    content: bytes,
):
    arena = create_arena(context, payload)
    try:
        return upload_payment_qr(context, arena["id"], filename, content_type, content)
    except Exception:
        get_supabase_admin_client().table("arenas").delete().eq("id", arena["id"]).execute()
        raise


def upload_payment_qr(
    context: AuthContext,
    arena_id: str,
    filename: str,
    content_type: str,
    content: bytes,
):
    owner = require_role(context, "owner")
    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    if _media_type_from_content_type(content_type) != "image":
        raise HTTPException(status_code=400, detail="Payment QR must be an image")
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Payment QR image must be 8 MB or smaller")

    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        extension = ".png"

    object_path = f"arenas/{arena_id}/payment-qr/{uuid4().hex}{extension}"
    admin_client = get_supabase_admin_client()
    try:
        admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).upload(
            object_path,
            content,
            file_options={
                "content-type": content_type,
                "cache-control": MEDIA_CACHE_CONTROL_SECONDS,
                "upsert": "false",
            },
        )
        public_url = admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).get_public_url(object_path)
    except Exception as exc:
        raise _storage_upload_error("Failed to upload payment QR", exc) from exc

    metadata = dict(arena.get("metadata") or {})
    previous_url = str(metadata.get("payment_qr_url") or "")
    metadata["payment_qr_url"] = public_url
    response = (
        _client(context)
        .table("arenas")
        .update({"metadata": metadata})
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )
    if not response.data:
        admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).remove([object_path])
        raise HTTPException(status_code=500, detail="Failed to attach payment QR")

    previous_path = _storage_path_from_public_url(previous_url)
    if previous_path:
        try:
            admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).remove([previous_path])
        except Exception:
            pass

    return response.data[0]


def upload_arena_media(
    context: AuthContext,
    arena_id: str,
    filename: str,
    content_type: str,
    content: bytes,
):
    owner = require_role(context, "owner")
    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    media_type = _media_type_from_content_type(content_type)
    if not media_type:
        raise HTTPException(status_code=400, detail="Only image and video uploads are allowed")

    max_bytes = MAX_VIDEO_BYTES if media_type == "video" else MAX_IMAGE_BYTES
    if len(content) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"{media_type.title()} uploads must be {max_mb} MB or smaller")

    extension = Path(filename or "").suffix.lower()
    allowed_extensions = ALLOWED_VIDEO_EXTENSIONS if media_type == "video" else ALLOWED_IMAGE_EXTENSIONS
    if extension not in allowed_extensions:
        extension = ".mp4" if media_type == "video" else ".jpg"

    object_path = f"arenas/{arena_id}/{media_type}s/{uuid4().hex}{extension}"
    admin_client = get_supabase_admin_client()

    try:
        admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).upload(
            object_path,
            content,
            file_options={
                "content-type": content_type,
                "cache-control": MEDIA_CACHE_CONTROL_SECONDS,
                "upsert": "false",
            },
        )
        public_url = admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).get_public_url(object_path)
    except Exception as exc:
        raise _storage_upload_error("Failed to upload arena media", exc) from exc

    images = list(arena.get("images") or [])
    images.append(public_url)
    response = (
        _client(context)
        .table("arenas")
        .update({"images": images})
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to attach arena media")

    return {
        "image_url": public_url,
        "media_url": public_url,
        "media_type": media_type,
        "images": response.data[0].get("images") or [],
    }


def upload_arena_image(
    context: AuthContext,
    arena_id: str,
    filename: str,
    content_type: str,
    content: bytes,
):
    return upload_arena_media(context, arena_id, filename, content_type, content)


def remove_arena_image(context: AuthContext, arena_id: str, image_url: str):
    owner = require_role(context, "owner")
    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    images = [image for image in list(arena.get("images") or []) if image != image_url]
    update_data = {"images": images}
    metadata = dict(arena.get("metadata") or {})
    if metadata.get("cover_media_url") == image_url:
        metadata.pop("cover_media_url", None)
        metadata.pop("cover_position", None)
        update_data["metadata"] = metadata

    response = (
        _client(context)
        .table("arenas")
        .update(update_data)
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to remove arena image")

    object_path = _storage_path_from_public_url(image_url)
    if object_path:
        try:
            get_supabase_admin_client().storage.from_(settings.ARENA_MEDIA_BUCKET).remove([object_path])
        except Exception:
            # Removing the database reference is the user-visible source of truth.
            pass

    return {"images": response.data[0].get("images") or []}


def reorder_arena_images(context: AuthContext, arena_id: str, images: list[str]):
    owner = require_role(context, "owner")
    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    existing_images = set(arena.get("images") or [])

    if set(images) != existing_images:
        raise HTTPException(status_code=400, detail="Media list does not match arena media")

    response = (
        _client(context)
        .table("arenas")
        .update({"images": images})
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )

    return {"images": response.data[0].get("images") or []}


def _media_type_from_content_type(content_type: str):
    normalized = (content_type or "").lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("video/"):
        return "video"
    return None


def _looks_like_video_url(url: str):
    return Path(url.split("?", 1)[0]).suffix.lower() in ALLOWED_VIDEO_EXTENSIONS


def set_arena_active(context: AuthContext, arena_id: str, is_active: bool):
    status = "active" if is_active else "inactive"
    return update_arena(
        context,
        arena_id,
        ArenaUpdate(is_active=is_active, status=status),
    )


def set_arena_booking_enabled(context: AuthContext, arena_id: str, booking_enabled: bool):
    owner = require_role(context, "owner")
    response = (
        _client(context)
        .table("arenas")
        .update({"booking_enabled": booking_enabled})
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    return response.data[0]


def delete_arena(context: AuthContext, arena_id: str):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)

    existing_booking = (
        _client(context)
        .table("bookings")
        .select("id")
        .eq("arena_id", arena_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing_booking:
        raise HTTPException(
            status_code=409,
            detail="Arena has booking history. Deactivate it instead of deleting.",
        )

    try:
        response = (
            _client(context)
            .table("arenas")
            .delete()
            .eq("id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    return {"deleted": bool(response.data)}


def list_owner_turfs(context: AuthContext, arena_id: str):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    response = (
        _client(context)
        .table("turfs")
        .select("*")
        .eq("arena_id", arena_id)
        .order("created_at")
        .execute()
    )
    return response.data or []


def list_public_turfs(arena_id: str):
    arena = get_arena_detail(arena_id)
    if not arena.get("is_active") or arena.get("status") != "active":
        raise HTTPException(status_code=404, detail="Arena not found")
    response = (
        get_supabase_client()
        .table("turfs")
        .select("*")
        .eq("arena_id", arena_id)
        .eq("is_active", True)
        .eq("status", "active")
        .order("created_at")
        .execute()
    )
    return response.data or []


def create_turf(context: AuthContext, arena_id: str, payload: TurfCreate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    data = _move_turf_details_to_metadata(_clean_payload(payload))
    data["arena_id"] = arena_id
    data["owner_id"] = owner["id"]
    data["is_active"] = data.get("status", "active") == "active"

    existing_turfs = (
        _client(context)
        .table("turfs")
        .select("*")
        .eq("arena_id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
        .data
        or []
    )
    matching_turf = next(
        (
            turf for turf in existing_turfs
            if str(turf.get("name") or "").strip().lower() == str(data.get("name") or "").strip().lower()
        ),
        None,
    )
    if matching_turf:
        existing_metadata = dict(matching_turf.get("metadata") or {})
        incoming_metadata = dict(data.get("metadata") or {})
        merged_sports = _normalize_turf_sports([
            *(existing_metadata.get("sports") or [matching_turf.get("sport")]),
            *(incoming_metadata.get("sports") or [data.get("sport")]),
        ])
        incoming_metadata["sports"] = merged_sports
        incoming_metadata["used_for_more_sports"] = len(merged_sports) > 1
        update_data = {
            **data,
            "sport": merged_sports[0] if merged_sports else data.get("sport"),
            "metadata": {**existing_metadata, **incoming_metadata},
        }
        try:
            response = (
                _client(context)
                .table("turfs")
                .update(update_data)
                .eq("id", matching_turf["id"])
                .eq("arena_id", arena_id)
                .eq("owner_id", owner["id"])
                .execute()
            )
        except APIError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to update existing turf")
        updated_turf = response.data[0]
        _ensure_full_day_slots_for_turf(arena_id, updated_turf)
        return updated_turf

    try:
        response = _client(context).table("turfs").insert(data).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create turf")
    created_turf = response.data[0]
    _ensure_full_day_slots_for_turf(arena_id, created_turf)
    return created_turf


def update_turf(context: AuthContext, arena_id: str, turf_id: str, payload: TurfUpdate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    existing = _ensure_owner_turf(context, owner["id"], arena_id, turf_id)
    data = _move_turf_details_to_metadata(_clean_payload(payload), existing.get("metadata") or {})
    if "status" in data:
        data["is_active"] = data["status"] == "active"
    if not data:
        raise HTTPException(status_code=400, detail="No turf fields to update")
    try:
        response = (
            _client(context)
            .table("turfs")
            .update(data)
            .eq("id", turf_id)
            .eq("arena_id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if not response.data:
        raise HTTPException(status_code=404, detail="Turf not found")
    updated_turf = response.data[0]
    _ensure_full_day_slots_for_turf(arena_id, updated_turf)
    return updated_turf


def upload_turf_media(
    context: AuthContext,
    arena_id: str,
    turf_id: str,
    filename: str,
    content_type: str,
    content: bytes,
):
    owner = require_role(context, "owner")
    turf = _ensure_owner_turf(context, owner["id"], arena_id, turf_id)
    media_type = _media_type_from_content_type(content_type)
    if not media_type:
        raise HTTPException(status_code=400, detail="Only image and video uploads are allowed")

    media = list(turf.get("media") or [])
    photo_count = sum(1 for item in media if not _looks_like_video_url(str(item)))
    video_count = sum(1 for item in media if _looks_like_video_url(str(item)))
    if media_type == "image" and photo_count >= 5:
        raise HTTPException(status_code=400, detail="A turf can have up to 5 photos")
    if media_type == "video" and video_count >= 1:
        raise HTTPException(status_code=400, detail="A turf can have only 1 video")

    max_bytes = 15 * 1024 * 1024 if media_type == "video" else 5 * 1024 * 1024
    if len(content) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"{media_type.title()} uploads must be {max_mb} MB or smaller")

    extension = Path(filename or "").suffix.lower()
    allowed_extensions = ALLOWED_VIDEO_EXTENSIONS if media_type == "video" else ALLOWED_IMAGE_EXTENSIONS
    if extension not in allowed_extensions:
        extension = ".mp4" if media_type == "video" else ".jpg"

    object_path = f"arenas/{arena_id}/turfs/{turf_id}/{media_type}s/{uuid4().hex}{extension}"
    admin_client = get_supabase_admin_client()
    try:
        admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).upload(
            object_path,
            content,
            file_options={
                "content-type": content_type,
                "cache-control": MEDIA_CACHE_CONTROL_SECONDS,
                "upsert": "false",
            },
        )
        public_url = admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).get_public_url(object_path)
    except Exception as exc:
        raise _storage_upload_error("Failed to upload turf media", exc) from exc

    media.append(public_url)
    response = (
        _client(context)
        .table("turfs")
        .update({"media": media})
        .eq("id", turf_id)
        .eq("arena_id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to attach turf media")
    return response.data[0]


def remove_turf_media(
    context: AuthContext,
    arena_id: str,
    turf_id: str,
    media_url: str,
):
    owner = require_role(context, "owner")
    turf = _ensure_owner_turf(context, owner["id"], arena_id, turf_id)
    current_media = list(turf.get("media") or [])
    if media_url not in current_media:
        raise HTTPException(status_code=404, detail="Turf media was not found")

    media = [item for item in current_media if item != media_url]
    response = (
        _client(context)
        .table("turfs")
        .update({"media": media})
        .eq("id", turf_id)
        .eq("arena_id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to remove turf media")

    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    arena_metadata = dict(arena.get("metadata") or {})
    if arena_metadata.get("cover_media_url") == media_url:
        arena_metadata.pop("cover_media_url", None)
        arena_metadata.pop("cover_position", None)
        (
            _client(context)
            .table("arenas")
            .update({"metadata": arena_metadata})
            .eq("id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )

    object_path = _storage_path_from_public_url(media_url)
    if object_path:
        try:
            get_supabase_admin_client().storage.from_(settings.ARENA_MEDIA_BUCKET).remove([object_path])
        except Exception:
            # The database reference is authoritative even if storage cleanup is delayed.
            pass

    return response.data[0]


def set_turf_active(context: AuthContext, arena_id: str, turf_id: str, is_active: bool):
    return update_turf(
        context,
        arena_id,
        turf_id,
        TurfUpdate(status="active" if is_active else "inactive"),
    )


def delete_turf(context: AuthContext, arena_id: str, turf_id: str):
    owner = require_role(context, "owner")
    turf = _ensure_owner_turf(context, owner["id"], arena_id, turf_id)

    slot_rows = (
        _client(context)
        .table("arena_slots")
        .select("id")
        .eq("arena_id", arena_id)
        .eq("turf_id", turf_id)
        .execute()
        .data
        or []
    )
    slot_ids = [slot["id"] for slot in slot_rows if slot.get("id")]

    existing_booking = (
        _client(context)
        .table("bookings")
        .select("id")
        .eq("arena_id", arena_id)
        .eq("turf_id", turf_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not existing_booking and slot_ids:
        existing_booking = (
            _client(context)
            .table("bookings")
            .select("id")
            .in_("slot_id", slot_ids)
            .limit(1)
            .execute()
            .data
            or []
        )
    if existing_booking:
        raise HTTPException(
            status_code=409,
            detail="Turf has booking history. Deactivate it instead of deleting.",
        )

    try:
        _client(context).table("arena_slots").delete().eq("arena_id", arena_id).eq("turf_id", turf_id).execute()
        response = (
            _client(context)
            .table("turfs")
            .delete()
            .eq("id", turf_id)
            .eq("arena_id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    arena = _ensure_owner_arena(context, owner["id"], arena_id)
    arena_metadata = dict(arena.get("metadata") or {})
    if arena_metadata.get("cover_media_url") in set(turf.get("media") or []):
        arena_metadata.pop("cover_media_url", None)
        arena_metadata.pop("cover_position", None)
        (
            _client(context)
            .table("arenas")
            .update({"metadata": arena_metadata})
            .eq("id", arena_id)
            .eq("owner_id", owner["id"])
            .execute()
        )

    storage_paths = [
        path
        for path in (_storage_path_from_public_url(str(item)) for item in (turf.get("media") or []))
        if path
    ]
    if storage_paths:
        try:
            get_supabase_admin_client().storage.from_(settings.ARENA_MEDIA_BUCKET).remove(storage_paths)
        except Exception:
            # Database deletion is the source of truth; storage cleanup can be retried later.
            pass

    return {"deleted": bool(response.data)}


def list_maintenance_windows(context: AuthContext, arena_id: str):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    response = (
        _client(context)
        .table("arena_maintenance_windows")
        .select("*")
        .eq("arena_id", arena_id)
        .order("start_at", desc=True)
        .execute()
    )
    return response.data or []


def create_maintenance_window(context: AuthContext, arena_id: str, payload: MaintenanceCreate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    if payload.turf_id:
        _ensure_owner_turf(context, owner["id"], arena_id, payload.turf_id)
    if payload.end_at <= payload.start_at:
        raise HTTPException(status_code=400, detail="Maintenance end time must be after start time")
    data = {
        "arena_id": arena_id,
        "owner_id": owner["id"],
        "turf_id": payload.turf_id,
        "start_at": payload.start_at.isoformat(),
        "end_at": payload.end_at.isoformat(),
        "reason": payload.reason,
        "status": "active",
    }
    try:
        response = _client(context).table("arena_maintenance_windows").insert(data).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to schedule maintenance")
    return response.data[0]


def cancel_maintenance_window(
    context: AuthContext,
    arena_id: str,
    maintenance_id: str,
    payload: MaintenanceCancel | None = None,
):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    metadata = {"cancel_reason": payload.reason} if payload and payload.reason else {}
    response = (
        _client(context)
        .table("arena_maintenance_windows")
        .update({"status": "cancelled", "metadata": metadata})
        .eq("id", maintenance_id)
        .eq("arena_id", arena_id)
        .eq("owner_id", owner["id"])
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    return response.data[0]


def list_available_slots(
    arena_id: str,
    slot_date: date | None = None,
    turf_id: str | None = None,
):
    arena_response = (
        get_supabase_client()
        .table("arenas")
        .select("id, booking_enabled")
        .eq("id", arena_id)
        .eq("is_active", True)
        .eq("status", "active")
        .maybe_single()
        .execute()
    )
    if not arena_response or not arena_response.data:
        raise HTTPException(status_code=404, detail="Arena not found")
    if arena_response.data.get("booking_enabled") is False:
        return []

    if turf_id:
        turf_response = (
            get_supabase_client()
            .table("turfs")
            .select("id")
            .eq("id", turf_id)
            .eq("arena_id", arena_id)
            .eq("is_active", True)
            .eq("status", "active")
            .maybe_single()
            .execute()
        )
        if not turf_response or not turf_response.data:
            return []

    if not slot_date or date.today() <= slot_date <= date.today() + timedelta(days=6):
        _ensure_full_day_slots_for_turfs(arena_id, turf_id=turf_id, active_only=True)
        _ensure_rolling_week_slots(arena_id)

    query = (
        get_supabase_client()
        .table("arena_slots")
        .select("*, turfs(*)")
        .eq("arena_id", arena_id)
        .eq("status", "active")
        .order("slot_date")
        .order("start_time")
    )

    if slot_date:
        query = query.eq("slot_date", slot_date.isoformat())
    if turf_id:
        query = query.eq("turf_id", turf_id)

    slots = query.execute().data or []
    available = []
    for slot in slots:
        slot_day = date.fromisoformat(str(slot.get("slot_date")))
        slot_start = time.fromisoformat(str(slot.get("start_time"))[:8])
        if datetime.combine(slot_day, slot_start) <= datetime.now():
            continue
        if int(slot.get("booked_count") or 0) >= int(slot.get("capacity") or 1):
            continue
        if _slot_overlaps_maintenance(arena_id, slot):
            continue
        available.append(slot)
    return available


def _full_day_slot_windows(slot_window_minutes: int):
    duration = max(1, min(int(slot_window_minutes or 60), 24 * 60))
    windows = []
    start_minutes = 0
    while start_minutes < 24 * 60:
        end_minutes = min(start_minutes + duration, 24 * 60)
        start_text = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}:00"
        end_text = (
            "23:59:59"
            if end_minutes == 24 * 60
            else f"{end_minutes // 60:02d}:{end_minutes % 60:02d}:00"
        )
        display_end = "24:00" if end_minutes == 24 * 60 else end_text[:5]
        windows.append((start_text, end_text, f"{start_text[:5]}-{display_end}"))
        start_minutes = end_minutes
    return windows


def _slot_price_for_date(turf: dict, slot_date: date) -> float:
    metadata = dict(turf.get("metadata") or {})
    price = float(turf.get("price_per_slot") or 0)
    weekday = slot_date.strftime("%a").casefold()
    peak_days = {str(value).strip().casefold() for value in metadata.get("peak_days") or []}
    discount_days = {str(value).strip().casefold() for value in metadata.get("discount_days") or []}
    if weekday in peak_days:
        price += float(metadata.get("peak_surcharge") or 0)
    if weekday in discount_days:
        price -= float(metadata.get("discount_amount") or 0)
    return max(price, 0)


def _ensure_full_day_slots_for_turfs(
    arena_id: str,
    turf_id: str | None = None,
    active_only: bool = False,
):
    query = get_supabase_admin_client().table("turfs").select("*").eq("arena_id", arena_id)
    if turf_id:
        query = query.eq("id", turf_id)
    if active_only:
        query = query.eq("is_active", True).eq("status", "active")
    for turf in query.execute().data or []:
        _ensure_full_day_slots_for_turf(arena_id, turf)


def _ensure_full_day_slots_for_turf(arena_id: str, turf: dict):
    turf_id = turf.get("id")
    if not turf_id:
        return []

    metadata = dict(turf.get("metadata") or {})
    duration = int(metadata.get("slot_window_minutes") or 60)
    windows = _full_day_slot_windows(duration)
    disabled_times = {str(value) for value in metadata.get("disabled_slot_times") or []}
    week_dates = [date.today() + timedelta(days=offset) for offset in range(7)]
    week_date_strings = [item.isoformat() for item in week_dates]
    client = get_supabase_admin_client()
    existing = (
        client.table("arena_slots")
        .select("id,slot_date,start_time,end_time,booked_count,status,metadata")
        .eq("arena_id", arena_id)
        .eq("turf_id", turf_id)
        .in_("slot_date", week_date_strings)
        .execute()
        .data
        or []
    )
    desired_times = {(start_time, end_time) for start_time, end_time, _ in windows}
    stale_ids = [
        item["id"]
        for item in existing
        if (item.get("metadata") or {}).get("auto_generated")
        and (str(item.get("start_time"))[:8], str(item.get("end_time"))[:8]) not in desired_times
        and int(item.get("booked_count") or 0) == 0
        and item.get("status") != "booked"
    ]
    if stale_ids:
        client.table("arena_slots").delete().in_("id", stale_ids).execute()
        stale_id_set = set(stale_ids)
        existing = [item for item in existing if item.get("id") not in stale_id_set]
    existing_keys = {
        (
            str(item.get("slot_date")),
            str(item.get("start_time"))[:8],
            str(item.get("end_time"))[:8],
        )
        for item in existing
    }

    rows = []
    for target_date in week_dates:
        for start_time, end_time, rule_key in windows:
            key = (target_date.isoformat(), start_time, end_time)
            if key in existing_keys:
                continue
            rows.append({
                "arena_id": arena_id,
                "turf_id": turf_id,
                "slot_date": target_date.isoformat(),
                "start_time": start_time,
                "end_time": end_time,
                "price": _slot_price_for_date(turf, target_date),
                "capacity": max(int(turf.get("capacity") or 1), 1),
                "booked_count": 0,
                "status": "blocked" if rule_key in disabled_times else "active",
                "metadata": {
                    "auto_generated": True,
                    "slot_window_minutes": duration,
                },
            })

    if not rows:
        return []
    try:
        return client.table("arena_slots").insert(rows).execute().data or []
    except APIError:
        # A concurrent request may have generated the same unique slots first.
        return []


def _set_recurring_slot_statuses(
    context: AuthContext,
    arena_id: str,
    turf_id: str,
    changes: list[RecurringSlotStatusChange],
):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    turf = _ensure_owner_turf(context, owner["id"], arena_id, turf_id)
    metadata = dict(turf.get("metadata") or {})
    disabled_times = {str(value) for value in metadata.get("disabled_slot_times") or []}

    normalized_changes: dict[tuple[time, time], str] = {}
    for change in changes:
        if change.end_time <= change.start_time and change.end_time != time(23, 59, 59):
            raise HTTPException(status_code=400, detail="Slot end time must be after its start time")
        display_end = "24:00" if change.end_time == time(23, 59, 59) else change.end_time.strftime("%H:%M")
        rule_key = f"{change.start_time.strftime('%H:%M')}-{display_end}"
        normalized_changes[(change.start_time, change.end_time)] = change.status
        if change.status == "blocked":
            disabled_times.add(rule_key)
        else:
            disabled_times.discard(rule_key)

    metadata["disabled_slot_times"] = sorted(disabled_times)
    client = _client(context)
    client.table("turfs").update({"metadata": metadata}).eq("id", turf_id).execute()

    updated_turf = {**turf, "metadata": metadata}
    _ensure_full_day_slots_for_turf(arena_id, updated_turf)
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(7)]
    updated_slots = []
    for (start_time, end_time), status in normalized_changes.items():
        response = (
            client.table("arena_slots")
            .update({"status": status})
            .eq("arena_id", arena_id)
            .eq("turf_id", turf_id)
            .eq("start_time", start_time.isoformat())
            .eq("end_time", end_time.isoformat())
            .in_("slot_date", week_dates)
            .neq("status", "booked")
            .execute()
        )
        updated_slots.extend(response.data or [])
    return updated_slots


def set_recurring_slot_status(
    context: AuthContext,
    arena_id: str,
    payload: RecurringSlotStatusUpdate,
):
    change = RecurringSlotStatusChange(
        start_time=payload.start_time,
        end_time=payload.end_time,
        status=payload.status,
    )
    return _set_recurring_slot_statuses(context, arena_id, payload.turf_id, [change])


def set_recurring_slot_statuses(
    context: AuthContext,
    arena_id: str,
    payload: RecurringSlotStatusesUpdate,
):
    return _set_recurring_slot_statuses(context, arena_id, payload.turf_id, payload.slots)


def create_slot(context: AuthContext, arena_id: str, payload: SlotCreate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    if payload.slot_date < date.today():
        raise HTTPException(status_code=400, detail="Slot date cannot be in the past")

    data = _clean_payload(payload)
    data["arena_id"] = arena_id
    if not data.get("turf_id"):
        raise HTTPException(status_code=400, detail="Create and select a turf before adding slots")
    _ensure_owner_turf(context, owner["id"], arena_id, data["turf_id"])

    try:
        response = _client(context).table("arena_slots").insert(data).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    created = response.data[0] if response.data else None
    if created:
        _create_slot_for_week_from_template(arena_id, created, payload.slot_date)

    return created


def copy_slots_to_date(context: AuthContext, arena_id: str, payload: SlotCopy):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)

    if payload.target_date < date.today():
        raise HTTPException(status_code=400, detail="Target date cannot be in the past")

    source_slots = (
        _client(context)
        .table("arena_slots")
        .select("*")
        .eq("arena_id", arena_id)
        .eq("slot_date", payload.source_date.isoformat())
        .order("start_time")
        .execute()
        .data
        or []
    )

    if not source_slots:
        raise HTTPException(status_code=404, detail="No slots found on the source date")

    target_slots = (
        _client(context)
        .table("arena_slots")
        .select("start_time,end_time,turf_id")
        .eq("arena_id", arena_id)
        .eq("slot_date", payload.target_date.isoformat())
        .execute()
        .data
        or []
    )
    existing_times = {
        (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8], str(slot.get("turf_id") or ""))
        for slot in target_slots
    }

    rows = []
    for slot in source_slots:
        time_key = (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8], str(slot.get("turf_id") or ""))
        if time_key in existing_times:
            continue

        metadata = dict(slot.get("metadata") or {})
        metadata["copied_from_date"] = payload.source_date.isoformat()
        rows.append({
            "arena_id": arena_id,
            "turf_id": slot.get("turf_id") or payload.turf_id,
            "slot_date": payload.target_date.isoformat(),
            "start_time": slot["start_time"],
            "end_time": slot["end_time"],
            "price": slot.get("price") or 0,
            "capacity": slot.get("capacity") or 1,
            "booked_count": 0,
            "status": "active" if slot.get("status") == "booked" else slot.get("status", "active"),
            "metadata": metadata,
        })

    if not rows:
        return []

    try:
        response = _client(context).table("arena_slots").insert(rows).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    return response.data or []


def _ensure_rolling_week_slots(arena_id: str):
    today = date.today()
    week_dates = [today + timedelta(days=offset) for offset in range(7)]
    week_date_strings = {item.isoformat() for item in week_dates}
    client = get_supabase_admin_client()
    all_slots = (
        client.table("arena_slots")
        .select("*")
        .eq("arena_id", arena_id)
        .order("slot_date")
        .order("start_time")
        .execute()
        .data
        or []
    )
    if not all_slots:
        return []

    slots_by_date: dict[str, list[dict]] = {}
    for slot in all_slots:
        slots_by_date.setdefault(str(slot.get("slot_date")), []).append(slot)

    existing_week_dates = week_date_strings.intersection(slots_by_date.keys())
    if existing_week_dates:
        source_date = max(existing_week_dates, key=lambda item: len(slots_by_date[item]))
    else:
        source_date = max(slots_by_date.keys(), key=lambda item: len(slots_by_date[item]))

    source_slots = slots_by_date[source_date]
    rows = []
    for target_date in week_dates:
        target_date_string = target_date.isoformat()
        existing_times = {
            (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8], str(slot.get("turf_id") or ""))
            for slot in slots_by_date.get(target_date_string, [])
        }
        for slot in source_slots:
            time_key = (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8], str(slot.get("turf_id") or ""))
            if time_key in existing_times:
                continue
            rows.append(_copy_slot_row(arena_id, slot, target_date, source_date))

    if not rows:
        return []

    try:
        return client.table("arena_slots").insert(rows).execute().data or []
    except APIError:
        return []


def _create_slot_for_week_from_template(arena_id: str, slot: dict, source_date: date):
    start_date = max(source_date, date.today())
    target_dates = [start_date + timedelta(days=offset) for offset in range(7)]
    client = get_supabase_admin_client()
    existing = (
        client.table("arena_slots")
        .select("slot_date,start_time,end_time,turf_id")
        .eq("arena_id", arena_id)
        .in_("slot_date", [target_date.isoformat() for target_date in target_dates])
        .execute()
        .data
        or []
    )
    existing_keys = {
        (str(item.get("slot_date")), str(item.get("start_time"))[:8], str(item.get("end_time"))[:8], str(item.get("turf_id") or ""))
        for item in existing
    }

    rows = []
    for target_date in target_dates:
        key = (target_date.isoformat(), str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8], str(slot.get("turf_id") or ""))
        if key in existing_keys:
            continue
        rows.append(_copy_slot_row(arena_id, slot, target_date, source_date.isoformat()))

    if rows:
        try:
            client.table("arena_slots").insert(rows).execute()
        except APIError:
            pass


def _copy_slot_row(arena_id: str, source_slot: dict, target_date: date, source_date: str):
    metadata = dict(source_slot.get("metadata") or {})
    metadata["auto_generated"] = True
    metadata["copied_from_date"] = str(source_date)
    return {
        "arena_id": arena_id,
        "turf_id": source_slot.get("turf_id"),
        "slot_date": target_date.isoformat(),
        "start_time": source_slot["start_time"],
        "end_time": source_slot["end_time"],
        "price": source_slot.get("price") or 0,
        "capacity": source_slot.get("capacity") or 1,
        "booked_count": 0,
        "status": "active" if source_slot.get("status") == "booked" else source_slot.get("status", "active"),
        "metadata": metadata,
    }


def update_slot(context: AuthContext, arena_id: str, slot_id: str, payload: SlotUpdate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    data = _clean_payload(payload)
    if data.get("turf_id"):
        _ensure_owner_turf(context, owner["id"], arena_id, data["turf_id"])

    if not data:
        raise HTTPException(status_code=400, detail="No slot fields to update")

    try:
        response = (
            _client(context)
            .table("arena_slots")
            .update(data)
            .eq("id", slot_id)
            .eq("arena_id", arena_id)
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Slot not found")

    return response.data[0]


def delete_slot(context: AuthContext, arena_id: str, slot_id: str):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    active_bookings = (
        _client(context)
        .table("bookings")
        .select("id")
        .eq("slot_id", slot_id)
        .in_("status", ["pending", "confirmed"])
        .limit(1)
        .execute()
    )

    if active_bookings.data:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a slot with active bookings. Block it instead.",
        )

    response = (
        _client(context)
        .table("arena_slots")
        .delete()
        .eq("id", slot_id)
        .eq("arena_id", arena_id)
        .execute()
    )

    return {"deleted": bool(response.data)}


def _storage_path_from_public_url(image_url: str):
    bucket_marker = settings.ARENA_MEDIA_BUCKET.replace(" ", "%20")
    marker = f"/storage/v1/object/public/{bucket_marker}/"
    if marker not in image_url:
        marker = f"/storage/v1/object/public/{settings.ARENA_MEDIA_BUCKET}/"
    if marker not in image_url:
        return None

    return image_url.split(marker, 1)[1].split("?", 1)[0]


def _arena_public_url(arena_id: str):
    return f"{settings.FRONTEND_URL.rstrip('/')}/explore/arena/{arena_id}"


def _ensure_owner_turf(context: AuthContext, owner_id: str, arena_id: str, turf_id: str):
    response = (
        _client(context)
        .table("turfs")
        .select("*")
        .eq("id", turf_id)
        .eq("arena_id", arena_id)
        .eq("owner_id", owner_id)
        .maybe_single()
        .execute()
    )
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Turf not found")
    return response.data


def get_public_arena_detail(arena_id: str):
    return _sanitize_public_arena(get_arena_detail(arena_id))


def get_arena_contact(context: AuthContext, arena_id: str):
    arena = get_arena_detail(arena_id)
    metadata = arena.get("metadata") or {}
    return {
        "contact_country_code": metadata.get("contact_country_code") or "",
        "contact_number": metadata.get("contact_number") or "",
    }


def track_arena_contact_event(
    context: AuthContext | None,
    arena_id: str,
    payload: ArenaContactEventCreate,
):
    arena = get_arena_detail(arena_id)
    client = get_supabase_admin_client()
    anonymous_id = str(payload.anonymous_id)
    user_id = str(context.user.id) if context else None

    try:
        if user_id:
            (
                client.table("arena_contact_events")
                .update({"user_id": user_id})
                .eq("anonymous_id", anonymous_id)
                .is_("user_id", "null")
                .execute()
            )

        if user_id and payload.event_id:
            existing = (
                client.table("arena_contact_events")
                .select("*")
                .eq("id", str(payload.event_id))
                .eq("arena_id", arena_id)
                .eq("anonymous_id", anonymous_id)
                .maybe_single()
                .execute()
            )
            if existing and existing.data:
                return existing.data

        response = client.table("arena_contact_events").insert({
            "arena_id": arena_id,
            "arena_name": arena.get("name") or "Arena",
            "user_id": user_id,
            "anonymous_id": anonymous_id,
            "event_type": payload.event_type,
        }).execute()
    except APIError as exc:
        detail = str(exc)
        if "arena_contact_events" in detail:
            raise HTTPException(
                status_code=503,
                detail="Contact tracking is not ready. Apply the latest Supabase migration.",
            ) from exc
        raise HTTPException(status_code=400, detail="Could not record contact action") from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Could not record contact action")
    return response.data[0]


def _slot_overlaps_maintenance(arena_id: str, slot: dict):
    slot_date = date.fromisoformat(str(slot.get("slot_date")))
    start_time = time.fromisoformat(str(slot.get("start_time"))[:8])
    end_time = time.fromisoformat(str(slot.get("end_time"))[:8])
    return _has_maintenance_overlap(arena_id, slot.get("turf_id"), slot_date, start_time, end_time)


def _has_maintenance_overlap(
    arena_id: str,
    turf_id: str | None,
    booking_date: date,
    start_time: time,
    end_time: time,
):
    booking_start = datetime.combine(booking_date, start_time)
    booking_end = datetime.combine(booking_date, end_time)
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
            return True
    return False


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _ensure_owner_arena(context: AuthContext, owner_id: str, arena_id: str):
    response = (
        _client(context)
        .table("arenas")
        .select("*")
        .eq("id", arena_id)
        .eq("owner_id", owner_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    return response.data
