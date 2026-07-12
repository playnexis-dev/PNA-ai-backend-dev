from fastapi import APIRouter, Depends

from app.core.auth_context import AuthContext, get_current_auth_context
from app.notifications.service import (
    delete_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/me")
async def notifications_me(
    context: AuthContext = Depends(get_current_auth_context),
):
    return list_notifications(context)


@router.patch("/read-all")
async def notifications_read_all(
    context: AuthContext = Depends(get_current_auth_context),
):
    return mark_all_notifications_read(context)


@router.patch("/{notification_id}/read")
async def notification_read(
    notification_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return mark_notification_read(context, notification_id)


@router.delete("/{notification_id}")
async def notification_delete(
    notification_id: str,
    context: AuthContext = Depends(get_current_auth_context),
):
    return delete_notification(context, notification_id)
