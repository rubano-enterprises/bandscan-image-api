"""Item-scoped image endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from ulid import ULID

from ..auth import verify_token
from ..config import get_settings
from ..database import (
    get_images_for_item,
    get_max_order_for_item,
    insert_image,
    update_image_orders,
    delete_images_for_item,
    set_primary_image,
    get_primary_image_for_item,
)
from ..models import (
    ImageMetadata,
    ImageListResponse,
    ImageUploadResponse,
    ImageReorderRequest,
    ImageReorderResponse,
    ErrorResponse,
)
from ..services import storage_service, image_service

settings = get_settings()
router = APIRouter(prefix="/items", tags=["items"])


def build_image_response(image_data: dict) -> ImageMetadata:
    """Build an ImageMetadata response from database row."""
    return ImageMetadata(
        id=image_data["id"],
        item_id=image_data["item_id"],
        url=f"{settings.base_url}/images/{image_data['id']}",
        thumbnail_url=f"{settings.base_url}/images/{image_data['id']}/thumbnail",
        display_order=image_data["display_order"],
        is_primary=bool(image_data.get("is_primary", 0)),
        description=image_data["description"],
        filename=image_data["filename"],
        content_type=image_data["content_type"],
        size_bytes=image_data["size_bytes"],
        width=image_data["width"],
        height=image_data["height"],
        created_at=image_data["created_at"],
    )


def generate_image_id() -> str:
    """Generate a unique image ID using ULID."""
    return f"img_{ULID()}"


@router.post(
    "/{item_id}/images",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def upload_image(
    item_id: str,
    file: UploadFile = File(...),
    order: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    _: str = Depends(verify_token),
):
    """
    Upload an image for an inventory item.

    The image will be processed to generate a thumbnail.
    """
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = storage_service.get_extension(file.filename)
    if ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(settings.allowed_extensions_list)}",
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB",
        )

    # Validate it's actually an image
    if not image_service.validate_image(content):
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Detect content type
    content_type = image_service.get_content_type(content)
    if not content_type:
        content_type = file.content_type or "application/octet-stream"

    # Get image dimensions
    try:
        width, height = image_service.get_image_dimensions(content)
    except Exception:
        width, height = None, None

    # Generate thumbnail
    try:
        thumbnail_content = image_service.create_thumbnail(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process image: {e}")

    # Generate IDs and filenames
    image_id = generate_image_id()
    stored_filename = storage_service.generate_stored_filename(file.filename)
    thumbnail_filename = storage_service.get_thumbnail_filename()

    # Determine order
    if order is None:
        order = await get_max_order_for_item(item_id) + 1

    # Save files
    await storage_service.save_file(image_id, stored_filename, content)
    await storage_service.save_file(image_id, thumbnail_filename, thumbnail_content)

    # Save metadata
    image_data = await insert_image(
        image_id=image_id,
        item_id=item_id,
        filename=file.filename,
        stored_filename=stored_filename,
        content_type=content_type,
        size_bytes=len(content),
        width=width,
        height=height,
        thumbnail_filename=thumbnail_filename,
        display_order=order,
        description=description,
    )

    return build_image_response(image_data)


@router.get(
    "/{item_id}/images",
    response_model=ImageListResponse,
)
async def list_images(
    item_id: str,
    _: str = Depends(verify_token),
):
    """List all images for an inventory item."""
    images = await get_images_for_item(item_id)

    return ImageListResponse(
        item_id=item_id,
        images=[build_image_response(img) for img in images],
        count=len(images),
    )


@router.put(
    "/{item_id}/images/order",
    response_model=ImageReorderResponse,
)
async def reorder_images(
    item_id: str,
    request: ImageReorderRequest,
    _: str = Depends(verify_token),
):
    """Reorder images for an inventory item."""
    await update_image_orders(item_id, request.image_ids)

    return ImageReorderResponse(
        item_id=item_id,
        reordered=True,
        order=request.image_ids,
    )


@router.delete(
    "/{item_id}/images",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_all_images(
    item_id: str,
    _: str = Depends(verify_token),
):
    """Delete all images for an inventory item."""
    images = await delete_images_for_item(item_id)

    # Delete all files
    for img in images:
        await storage_service.delete_image_files(img["id"])

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{item_id}/images/{image_id}/primary",
    response_model=ImageMetadata,
    responses={404: {"model": ErrorResponse}},
)
async def set_primary(
    item_id: str,
    image_id: str,
    _: str = Depends(verify_token),
):
    """Set an image as the primary image for an item."""
    from ..database import get_image_by_id

    # Verify image exists and belongs to item
    image_data = await get_image_by_id(image_id)
    if not image_data or image_data["item_id"] != item_id:
        raise HTTPException(status_code=404, detail="Image not found")

    await set_primary_image(item_id, image_id)

    # Refresh image data
    image_data = await get_image_by_id(image_id)
    return build_image_response(image_data)


@router.get(
    "/{item_id}/images/primary",
    response_model=ImageMetadata,
    responses={404: {"model": ErrorResponse}},
)
async def get_primary(
    item_id: str,
    _: str = Depends(verify_token),
):
    """Get the primary image for an item (or first image if none set)."""
    image_data = await get_primary_image_for_item(item_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="No images found for item")

    return build_image_response(image_data)
