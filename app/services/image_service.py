"""Image processing service for thumbnails and resizing."""

import io
from typing import Tuple, Optional
from PIL import Image, ExifTags

from ..config import get_settings

settings = get_settings()


def apply_exif_orientation(img: Image.Image) -> Image.Image:
    """
    Apply EXIF orientation to the image to correct rotation.

    Mobile devices often save photos with EXIF orientation data rather than
    actually rotating the pixels. This ensures images display correctly.
    """
    try:
        # Get EXIF data
        exif = img._getexif()
        if exif is None:
            return img

        # Find orientation tag
        orientation_key = None
        for key, value in ExifTags.TAGS.items():
            if value == "Orientation":
                orientation_key = key
                break

        if orientation_key is None or orientation_key not in exif:
            return img

        orientation = exif[orientation_key]

        # Apply rotation/flip based on orientation value
        if orientation == 2:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 4:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif orientation == 5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(270, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 7:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(90, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)

        return img
    except (AttributeError, KeyError, IndexError):
        # No EXIF data or can't process it
        return img


def get_image_dimensions(image_data: bytes) -> Tuple[int, int]:
    """
    Get the dimensions of an image.

    Args:
        image_data: Raw image bytes

    Returns:
        Tuple of (width, height)
    """
    with Image.open(io.BytesIO(image_data)) as img:
        return img.size


def create_thumbnail(image_data: bytes, size: Optional[int] = None) -> bytes:
    """
    Create a thumbnail from image data.

    Args:
        image_data: Raw image bytes
        size: Thumbnail size (default from settings)

    Returns:
        JPEG thumbnail bytes
    """
    if size is None:
        size = settings.thumbnail_size

    with Image.open(io.BytesIO(image_data)) as img:
        # Apply EXIF orientation to correct rotation from mobile photos
        img = apply_exif_orientation(img)

        # Convert to RGB if necessary (for PNG with transparency, etc.)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Create thumbnail maintaining aspect ratio
        img.thumbnail((size, size), Image.Resampling.LANCZOS)

        # Save as JPEG
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()


def resize_image(
    image_data: bytes,
    width: Optional[int] = None,
    height: Optional[int] = None,
    content_type: str = "image/jpeg",
) -> bytes:
    """
    Resize an image maintaining aspect ratio.

    Args:
        image_data: Raw image bytes
        width: Target width (optional)
        height: Target height (optional)
        content_type: Original content type for format detection

    Returns:
        Resized image bytes
    """
    if width is None and height is None:
        return image_data

    with Image.open(io.BytesIO(image_data)) as img:
        # Apply EXIF orientation to correct rotation from mobile photos
        img = apply_exif_orientation(img)

        original_width, original_height = img.size

        # Calculate new dimensions maintaining aspect ratio
        if width and height:
            # Fit within both constraints
            ratio = min(width / original_width, height / original_height)
        elif width:
            ratio = width / original_width
        else:
            ratio = height / original_height

        new_width = int(original_width * ratio)
        new_height = int(original_height * ratio)

        # Resize
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Determine output format
        format_map = {
            "image/jpeg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WEBP",
        }
        output_format = format_map.get(content_type, "JPEG")

        # Convert to RGB for JPEG
        if output_format == "JPEG" and resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")

        output = io.BytesIO()
        save_kwargs = {"format": output_format}
        if output_format == "JPEG":
            save_kwargs["quality"] = 85
            save_kwargs["optimize"] = True

        resized.save(output, **save_kwargs)
        return output.getvalue()


def validate_image(image_data: bytes) -> bool:
    """
    Validate that data is a valid image.

    Args:
        image_data: Raw bytes to validate

    Returns:
        True if valid image, False otherwise
    """
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            img.verify()
        return True
    except Exception:
        return False


def get_content_type(image_data: bytes) -> Optional[str]:
    """
    Detect the content type of image data.

    Args:
        image_data: Raw image bytes

    Returns:
        MIME type string or None if not detected
    """
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            format_map = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "GIF": "image/gif",
                "WEBP": "image/webp",
            }
            return format_map.get(img.format)
    except Exception:
        return None
