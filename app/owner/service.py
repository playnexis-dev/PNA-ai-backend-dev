from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.supabase import get_supabase_client


async def create_owner(
    payload,
    access_token: str | None = None,
):
    supabase = get_supabase_client(access_token)

    existing_owner = (
        supabase
        .table("owners")
        .select("*")
        .eq("email", payload.email)
        .execute()
    )

    if existing_owner.data:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    if payload.user_id:
        existing_user_profile = (
            supabase
            .table("owners")
            .select("*")
            .eq("user_id", payload.user_id)
            .execute()
        )

        if existing_user_profile.data:
            raise HTTPException(
                status_code=400,
                detail="Owner profile already exists for this user",
            )

    insert_payload = {
        "full_name": payload.full_name,
        "email": payload.email,
        "phone": payload.phone,
        "company_name": payload.company_name,
        "phone_verified": bool(payload.phone),
    }

    if payload.user_id:
        insert_payload["user_id"] = payload.user_id

    try:
        response = (
            supabase
            .table("owners")
            .insert(insert_payload)
            .execute()
        )
    except APIError as exc:
        if "phone_verified" in (exc.message or ""):
            insert_payload.pop("phone_verified", None)
            response = (
                supabase
                .table("owners")
                .insert(insert_payload)
                .execute()
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=exc.message,
            ) from exc

    if not response.data:
        raise HTTPException(
            status_code=500,
            detail="Failed to create owner profile",
        )

    return response.data[0]
