from fastapi import APIRouter, Depends

from app.core.auth_context import AuthContext, get_current_auth_context
from app.reviews.schemas import ReviewCreate
from app.reviews.service import create_review, list_arena_reviews

router = APIRouter(prefix="/reviews", tags=["Reviews"])


@router.get("/arena/{arena_id}")
async def arena_reviews(arena_id: str):
    return list_arena_reviews(arena_id)


@router.post("")
async def player_create_review(
    payload: ReviewCreate,
    context: AuthContext = Depends(get_current_auth_context),
):
    return create_review(context, payload)
