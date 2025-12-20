"""Image endpoints for individual image operations."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..auth import verify_token
from ..config import get_settings
from ..database import get_image_by_id, update_image, delete_image
from ..models import ImageMetadata, ImageUpdateRequest, ErrorResponse
from ..services import storage_service, image_service

settings = get_settings()
router = APIRouter(prefix="/images", tags=["images"])


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


@router.get(
    "/{image_id}",
    responses={404: {"model": ErrorResponse}},
)
async def get_image(
    image_id: str,
    width: Optional[int] = Query(None, gt=0, le=4000),
    height: Optional[int] = Query(None, gt=0, le=4000),
    _: str = Depends(verify_token),
):
    """
    Get an image by ID.

    Optionally resize by specifying width and/or height.
    """
    image_data = await get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    # Read the file
    content = await storage_service.read_file(image_id, image_data["stored_filename"])
    if content is None:
        raise HTTPException(status_code=404, detail="Image file not found")

    # Resize if requested
    if width or height:
        content = image_service.resize_image(
            content, width=width, height=height, content_type=image_data["content_type"]
        )

    return Response(content=content, media_type=image_data["content_type"])


@router.get(
    "/{image_id}/thumbnail",
    responses={404: {"model": ErrorResponse}},
)
async def get_thumbnail(
    image_id: str,
    _: str = Depends(verify_token),
):
    """Get the thumbnail for an image."""
    image_data = await get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    thumbnail_filename = image_data.get("thumbnail_filename")
    if not thumbnail_filename:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    content = await storage_service.read_file(image_id, thumbnail_filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return Response(content=content, media_type="image/jpeg")


@router.get(
    "/{image_id}/metadata",
    response_model=ImageMetadata,
    responses={404: {"model": ErrorResponse}},
)
async def get_image_metadata(
    image_id: str,
    _: str = Depends(verify_token),
):
    """Get metadata for an image."""
    image_data = await get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    return build_image_response(image_data)


@router.patch(
    "/{image_id}",
    response_model=ImageMetadata,
    responses={404: {"model": ErrorResponse}},
)
async def update_image_metadata(
    image_id: str,
    request: ImageUpdateRequest,
    _: str = Depends(verify_token),
):
    """Update image metadata (order, description)."""
    image_data = await get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    updated = await update_image(
        image_id,
        display_order=request.order,
        description=request.description,
    )

    return build_image_response(updated)


@router.delete(
    "/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
async def delete_image_endpoint(
    image_id: str,
    _: str = Depends(verify_token),
):
    """Delete an image."""
    image_data = await delete_image(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    # Delete files
    await storage_service.delete_image_files(image_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
