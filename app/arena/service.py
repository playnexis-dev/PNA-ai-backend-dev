from datetime import date, time, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.arena.schemas import ArenaCreate, ArenaUpdate, SlotCopy, SlotCreate, SlotUpdate
from app.core.auth_context import AuthContext, require_role
from app.core.config import settings
from app.core.supabase import get_supabase_admin_client, get_supabase_client


def _client(context: AuthContext):
    return get_supabase_client(context.access_token)


def _clean_payload(payload):
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(exclude_unset=True, mode="json")
    else:
        data = dict(payload)

    return {key: value for key, value in data.items() if value is not None}


def list_active_arenas(
    city: str | None = None,
    sport: str | None = None,
):
    client = get_supabase_client()
    query = (
        client.table("arenas")
        .select("*, arena_slots(*)")
        .eq("is_active", True)
        .eq("status", "active")
        .order("rating", desc=True)
    )

    if city:
        query = query.ilike("city", f"%{city}%")

    if sport:
        query = query.ilike("sport", f"%{sport}%")

    return query.execute().data or []


def get_arena_detail(arena_id: str):
    client = get_supabase_client()
    response = (
        client.table("arenas")
        .select("*, arena_slots(*), reviews(*, players(full_name, avatar_url))")
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
        .select("*, arena_slots(*)")
        .eq("owner_id", owner["id"])
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def list_owner_slots(context: AuthContext, arena_id: str, slot_date: date | None = None):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    if not slot_date or date.today() <= slot_date <= date.today() + timedelta(days=6):
        _ensure_rolling_week_slots(arena_id)

    query = (
        _client(context)
        .table("arena_slots")
        .select("*")
        .eq("arena_id", arena_id)
        .order("slot_date")
        .order("start_time")
    )

    if slot_date:
        query = query.eq("slot_date", slot_date.isoformat())

    return query.execute().data or []


def create_arena(context: AuthContext, payload: ArenaCreate):
    owner = require_role(context, "owner")
    data = _clean_payload(payload)
    data["owner_id"] = owner["id"]
    data["status"] = "active"
    data["is_active"] = True
    data["price_unit"] = "slot"

    try:
        response = _client(context).table("arenas").insert(data).execute()
    except APIError as exc:
        raise _arena_data_error(exc) from exc

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create arena")

    arena = response.data[0]
    _ensure_rolling_week_slots(arena["id"])
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
        .select("id, images")
        .eq("id", arena_id)
        .eq("owner_id", owner["id"])
        .maybe_single()
        .execute()
    )

    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Arena not found")

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
                "upsert": "false",
            },
        )
        public_url = admin_client.storage.from_(settings.ARENA_MEDIA_BUCKET).get_public_url(object_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to upload arena media: {exc}") from exc

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

    response = (
        _client(context)
        .table("arenas")
        .update({"images": images})
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


def set_arena_active(context: AuthContext, arena_id: str, is_active: bool):
    status = "active" if is_active else "inactive"
    return update_arena(
        context,
        arena_id,
        ArenaUpdate(is_active=is_active, status=status),
    )


def list_available_slots(arena_id: str, slot_date: date | None = None):
    if slot_date and date.today() <= slot_date <= date.today() + timedelta(days=6):
        _ensure_rolling_week_slots(arena_id)

    query = (
        get_supabase_client()
        .table("arena_slots")
        .select("*")
        .eq("arena_id", arena_id)
        .eq("status", "active")
        .order("slot_date")
        .order("start_time")
    )

    if slot_date:
        query = query.eq("slot_date", slot_date.isoformat())

    slots = query.execute().data or []
    return [slot for slot in slots if int(slot.get("booked_count") or 0) < int(slot.get("capacity") or 1)]


def create_slot(context: AuthContext, arena_id: str, payload: SlotCreate):
    owner = require_role(context, "owner")
    _ensure_owner_arena(context, owner["id"], arena_id)
    if payload.slot_date < date.today():
        raise HTTPException(status_code=400, detail="Slot date cannot be in the past")

    data = _clean_payload(payload)
    data["arena_id"] = arena_id

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
        .select("start_time,end_time")
        .eq("arena_id", arena_id)
        .eq("slot_date", payload.target_date.isoformat())
        .execute()
        .data
        or []
    )
    existing_times = {
        (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8])
        for slot in target_slots
    }

    rows = []
    for slot in source_slots:
        time_key = (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8])
        if time_key in existing_times:
            continue

        metadata = dict(slot.get("metadata") or {})
        metadata["copied_from_date"] = payload.source_date.isoformat()
        rows.append({
            "arena_id": arena_id,
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
        arena = (
            client.table("arenas")
            .select("base_price")
            .eq("id", arena_id)
            .maybe_single()
            .execute()
            .data
            or {}
        )
        return _create_default_week_slots(arena_id, float(arena.get("base_price") or 0))

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
            (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8])
            for slot in slots_by_date.get(target_date_string, [])
        }
        for slot in source_slots:
            time_key = (str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8])
            if time_key in existing_times:
                continue
            rows.append(_copy_slot_row(arena_id, slot, target_date, source_date))

    if not rows:
        return []

    try:
        return client.table("arena_slots").insert(rows).execute().data or []
    except APIError:
        return []


def _create_default_week_slots(arena_id: str, price: float):
    today = date.today()
    rows = []
    for offset in range(7):
        slot_date = today + timedelta(days=offset)
        for hour in range(6, 19):
            rows.append({
                "arena_id": arena_id,
                "slot_date": slot_date.isoformat(),
                "start_time": time(hour, 0).isoformat(),
                "end_time": time(hour + 1, 0).isoformat(),
                "price": price,
                "capacity": 1,
                "booked_count": 0,
                "status": "active",
                "metadata": {"auto_generated": True, "default_template": True},
            })

    try:
        return get_supabase_admin_client().table("arena_slots").insert(rows).execute().data or []
    except APIError:
        return []


def _create_slot_for_week_from_template(arena_id: str, slot: dict, source_date: date):
    start_date = max(source_date, date.today())
    target_dates = [start_date + timedelta(days=offset) for offset in range(7)]
    client = get_supabase_admin_client()
    existing = (
        client.table("arena_slots")
        .select("slot_date,start_time,end_time")
        .eq("arena_id", arena_id)
        .in_("slot_date", [target_date.isoformat() for target_date in target_dates])
        .execute()
        .data
        or []
    )
    existing_keys = {
        (str(item.get("slot_date")), str(item.get("start_time"))[:8], str(item.get("end_time"))[:8])
        for item in existing
    }

    rows = []
    for target_date in target_dates:
        key = (target_date.isoformat(), str(slot.get("start_time"))[:8], str(slot.get("end_time"))[:8])
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


def _ensure_owner_arena(context: AuthContext, owner_id: str, arena_id: str):
    response = (
        _client(context)
        .table("arenas")
        .select("id, images")
        .eq("id", arena_id)
        .eq("owner_id", owner_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Arena not found")

    return response.data
