"""Pydantic models for API requests and responses."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ImageMetadata(BaseModel):
    """Image metadata response model."""

    id: str
    item_id: str
    url: str
    thumbnail_url: str
    order: int = Field(alias="display_order", default=0)
    is_primary: bool = False
    description: Optional[str] = None
    filename: str
    content_type: str
    size_bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime

    class Config:
        populate_by_name = True


class ImageListResponse(BaseModel):
    """Response for listing images."""

    item_id: str
    images: List[ImageMetadata]
    count: int


class ImageUploadResponse(ImageMetadata):
    """Response for image upload - same as metadata."""

    pass


class ImageUpdateRequest(BaseModel):
    """Request for updating image metadata."""

    order: Optional[int] = None
    description: Optional[str] = None


class ImageReorderRequest(BaseModel):
    """Request for reordering images."""

    image_ids: List[str]


class ImageReorderResponse(BaseModel):
    """Response for image reorder."""

    item_id: str
    reordered: bool
    order: List[str]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str


class ErrorResponse(BaseModel):
    """Error response model."""

    detail: str


# Device Token Models

class DeviceTokenRegisterRequest(BaseModel):
    """Request for registering a device token."""

    student_uid: str
    band_id: str
    token: str
    platform: str = Field(..., pattern="^(ios|android)$")


class DeviceTokenResponse(BaseModel):
    """Device token response model."""

    id: int
    student_uid: str
    band_id: str
    token: str
    platform: str
    created_at: datetime
    last_seen: datetime


# Notification Models

class SendNotificationRequest(BaseModel):
    """Request for sending a notification to selected students."""

    band_id: str
    sender_email: str
    title: str
    body: str
    recipient_uids: List[str] = Field(..., min_length=1)
    data: Optional[dict] = None  # Optional custom data payload


class NotificationResponse(BaseModel):
    """Notification response model."""

    id: str
    band_id: str
    sender_email: str
    title: str
    body: str
    recipient_uids: List[str]
    sent_at: datetime
    success_count: int
    failure_count: int


class NotificationSendResponse(BaseModel):
    """Response for sending a notification."""

    notification_id: str
    success_count: int
    failure_count: int
    total_recipients: int
    message: str


class NotificationListResponse(BaseModel):
    """Response for listing notifications."""

    band_id: str
    notifications: List[NotificationResponse]
    count: int
    limit: int
    offset: int
