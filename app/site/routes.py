from fastapi import APIRouter

from app.site.schemas import HomeVisitResponse
from app.site.service import record_home_page_visit


router = APIRouter(prefix="/public", tags=["Public Website"])


@router.post("/visits/home", response_model=HomeVisitResponse)
async def home_page_visit():
    return HomeVisitResponse(visitor_count=record_home_page_visit())
