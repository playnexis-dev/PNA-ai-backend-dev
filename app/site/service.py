import logging

from fastapi import HTTPException

from app.core.supabase import get_supabase_client


logger = logging.getLogger(__name__)

HOME_COUNTER_KEY = "home_page"
HOME_COUNTER_BASELINE = 8910


def record_home_page_visit() -> int:
    try:
        response = get_supabase_client().rpc(
            "increment_site_counter",
            {
                "p_counter_key": HOME_COUNTER_KEY,
                "p_baseline": HOME_COUNTER_BASELINE,
            },
        ).execute()
        value = response.data
        if isinstance(value, list):
            value = value[0] if value else None
        return int(value)
    except Exception as exc:
        logger.exception("Failed to increment the public homepage visitor counter")
        raise HTTPException(
            status_code=503,
            detail="Visitor count is temporarily unavailable",
        ) from exc
