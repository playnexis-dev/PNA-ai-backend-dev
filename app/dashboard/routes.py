from fastapi import APIRouter, Depends

from app.core.auth_context import AuthContext, get_current_auth_context
from app.dashboard.service import get_owner_dashboard, get_player_dashboard

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/player")
async def player_dashboard(
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_player_dashboard(context)


@router.get("/owner")
async def owner_dashboard(
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_owner_dashboard(context)
