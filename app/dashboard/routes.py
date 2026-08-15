from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth_context import AuthContext, get_current_auth_context
from app.dashboard.service import get_owner_dashboard, get_player_dashboard

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/player")
async def player_dashboard(
    city: str | None = Query(default=None),
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float = Query(default=20, ge=1, le=50),
    context: AuthContext = Depends(get_current_auth_context),
):
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=422, detail="Latitude and longitude must be provided together")
    return get_player_dashboard(
        context,
        city=city,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


@router.get("/owner")
async def owner_dashboard(
    context: AuthContext = Depends(get_current_auth_context),
):
    return get_owner_dashboard(context)
