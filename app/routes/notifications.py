"""Notification management endpoints."""

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query

from ..auth import verify_token
from ..database import (
    get_device_tokens_for_students,
    insert_notification,
    get_notifications_for_band,
    get_notification_by_id,
)
from ..models import (
    SendNotificationRequest,
    NotificationSendResponse,
    NotificationListResponse,
    NotificationResponse,
)
from ..services.push_service import push_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.post("/send", response_model=NotificationSendResponse, status_code=status.HTTP_201_CREATED)
async def send_notification(
    request: SendNotificationRequest,
    _token: str = Depends(verify_token),
):
    """
    Send a push notification to selected students.

    Flow:
    1. Get device tokens for recipient students
    2. Send notifications via FCM/APNs
    3. Log the notification with results

    Admin must provide:
    - band_id: Which school/band
    - sender_email: Admin's email
    - title: Notification title
    - body: Notification message
    - recipient_uids: List of student UIDs to notify
    """
    try:
        # Get device tokens for the recipient students
        tokens = await get_device_tokens_for_students(
            student_uids=request.recipient_uids,
            band_id=request.band_id,
        )

        if not tokens:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No device tokens found for specified students"
            )

        logger.info(
            f"Sending notification to {len(tokens)} devices for {len(request.recipient_uids)} students"
        )

        # Send the notification
        success_count, failure_count = await push_service.send_notification(
            tokens=tokens,
            title=request.title,
            body=request.body,
            data=request.data,
        )

        # Log the notification
        notification_id = f"notif_{uuid.uuid4().hex[:12]}"
        await insert_notification(
            notification_id=notification_id,
            band_id=request.band_id,
            sender_email=request.sender_email,
            title=request.title,
            body=request.body,
            recipient_uids=request.recipient_uids,
            success_count=success_count,
            failure_count=failure_count,
        )

        logger.info(
            f"Notification {notification_id}: {success_count} succeeded, {failure_count} failed"
        )

        return NotificationSendResponse(
            notification_id=notification_id,
            success_count=success_count,
            failure_count=failure_count,
            total_recipients=len(tokens),
            message=f"Notification sent to {success_count}/{len(tokens)} devices"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send notification: {str(e)}"
        )


@router.get("/{band_id}", response_model=NotificationListResponse)
async def list_notifications(
    band_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _token: str = Depends(verify_token),
):
    """
    List recent notifications for a band.

    Returns notification history with pagination.
    """
    try:
        notifications = await get_notifications_for_band(
            band_id=band_id,
            limit=limit,
            offset=offset,
        )

        # Convert recipient_uids from comma-separated string to list
        for notif in notifications:
            if isinstance(notif.get("recipient_uids"), str):
                notif["recipient_uids"] = notif["recipient_uids"].split(",")

        return NotificationListResponse(
            band_id=band_id,
            notifications=[NotificationResponse(**n) for n in notifications],
            count=len(notifications),
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        logger.error(f"Error listing notifications: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list notifications: {str(e)}"
        )


@router.get("/{band_id}/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    band_id: str,
    notification_id: str,
    _token: str = Depends(verify_token),
):
    """
    Get details of a specific notification.
    """
    try:
        notification = await get_notification_by_id(notification_id)

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )

        if notification["band_id"] != band_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Notification does not belong to specified band"
            )

        # Convert recipient_uids from comma-separated string to list
        if isinstance(notification.get("recipient_uids"), str):
            notification["recipient_uids"] = notification["recipient_uids"].split(",")

        return NotificationResponse(**notification)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notification: {str(e)}"
        )
