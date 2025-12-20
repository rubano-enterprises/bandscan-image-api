"""Device token management endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_token
from ..database import upsert_device_token, delete_device_token, update_token_last_seen
from ..models import DeviceTokenRegisterRequest, DeviceTokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["Device Tokens"])


@router.post("/register", response_model=DeviceTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_device_token(
    request: DeviceTokenRegisterRequest,
    _token: str = Depends(verify_token),
):
    """
    Register or update a device token for push notifications.

    This endpoint should be called when:
    - Student logs in
    - App starts with valid session
    - Token is refreshed by the OS

    Only one token per student per band is stored (last device wins).
    """
    try:
        result = await upsert_device_token(
            student_uid=request.student_uid,
            band_id=request.band_id,
            token=request.token,
            platform=request.platform,
        )

        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register device token"
            )

        logger.info(
            f"Registered {request.platform} token for student {request.student_uid} in band {request.band_id}"
        )

        return DeviceTokenResponse(**result)

    except Exception as e:
        logger.error(f"Error registering device token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register device token: {str(e)}"
        )


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device_token(
    token: str,
    _token: str = Depends(verify_token),
):
    """
    Unregister a device token.

    This should be called when:
    - Student logs out
    - Student opts out of notifications
    """
    try:
        deleted = await delete_device_token(token)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device token not found"
            )

        logger.info(f"Unregistered device token: {token[:20]}...")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unregistering device token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unregister device token: {str(e)}"
        )


@router.post("/{token}/ping", status_code=status.HTTP_200_OK)
async def ping_device_token(
    token: str,
    _token: str = Depends(verify_token),
):
    """
    Update the last_seen timestamp for a device token.

    Useful for tracking active devices.
    """
    try:
        await update_token_last_seen(token)
        return {"message": "Token last_seen updated"}

    except Exception as e:
        logger.error(f"Error updating token last_seen: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update token: {str(e)}"
        )
