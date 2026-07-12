from fastapi import APIRouter, Depends

from app.core.auth_context import AuthContext, get_current_auth_context
from app.profile.schemas import ProfileUpdate
from app.profile.service import get_current_profile, update_current_profile

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
