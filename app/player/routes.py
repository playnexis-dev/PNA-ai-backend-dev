from fastapi import (
    APIRouter,
    HTTPException,
)

from app.player.schemas import PlayerRegister
from app.player.service import create_player

router = APIRouter(
    prefix="/players",
    tags=["Players"],
)


@router.post("/register")
async def register_player(
    payload: PlayerRegister,
):
    try:
        return await create_player(payload)

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
