from fastapi import APIRouter, Depends

from app.core.auth_context import AuthContext, get_current_auth_context, require_verified_email
from app.profile.schemas import AccountDeleteRequest, ProfileUpdate
from app.profile.service import delete_current_account, get_current_profile, update_current_profile

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("/me")
async def profile_me(
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_current_profile(context)


@router.patch("/me")
async def update_profile_me(
    payload: ProfileUpdate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return update_current_profile(context, payload)


@router.delete("/me")
async def delete_profile_me(
    payload: AccountDeleteRequest,
    context: AuthContext = Depends(get_current_auth_context),
):
    require_verified_email(context)
    return delete_current_account(context, payload)
