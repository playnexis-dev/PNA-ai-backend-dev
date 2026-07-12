import logging
from urllib.parse import urlencode

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.owner.routes import router as owner_router
from app.player.routes import router as player_router
from app.arena.routes import router as arena_router
from app.booking.routes import router as booking_router
from app.dashboard.routes import router as dashboard_router
from app.notifications.routes import router as notifications_router
from app.profile.routes import router as profile_router
from app.reviews.routes import router as reviews_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


app = FastAPI(
    title="PlayNexis API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.auth.routes import (
    router as auth_router,
)
app.include_router(owner_router)
app.include_router(player_router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(arena_router)
app.include_router(booking_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(reviews_router)


@app.get("/")
async def root(
    error: str | None = Query(default=None),
    error_code: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    if error or error_code or error_description:
        params = urlencode({
            "error": error_description or error_code or error or "Google login failed",
        })
        return RedirectResponse(f"{settings.FRONTEND_URL}/auth/callback?{params}")

    return {
        "message": "PlayNexis Backend Running"
    }
