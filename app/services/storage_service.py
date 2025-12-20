"""File storage service for images."""

import os
import shutil
from pathlib import Path
from typing import Optional
import aiofiles
import aiofiles.os

from ..config import get_settings

settings = get_settings()


def get_image_directory(image_id: str) -> Path:
    """Get the directory path for an image based on its ID."""
    # Use first 2 characters for sharding to avoid too many files in one directory
    prefix = image_id[:2] if len(image_id) >= 2 else image_id
    return Path(settings.images_path) / prefix / image_id


async def ensure_directory(path: Path) -> None:
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)


async def save_file(image_id: str, filename: str, content: bytes) -> str:
    """
    Save a file to storage.

    Args:
        image_id: The image ID
        filename: The filename to save as
        content: The file content

    Returns:
        The full path to the saved file
    """
    directory = get_image_directory(image_id)
    await ensure_directory(directory)

    file_path = directory / filename
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    return str(file_path)


async def read_file(image_id: str, filename: str) -> Optional[bytes]:
    """
    Read a file from storage.

    Args:
        image_id: The image ID
        filename: The filename to read

    Returns:
        The file content or None if not found
    """
    file_path = get_image_directory(image_id) / filename

    if not file_path.exists():
        return None

    async with aiofiles.open(file_path, "rb") as f:
        return await f.read()


async def delete_image_files(image_id: str) -> bool:
    """
    Delete all files for an image.

    Args:
        image_id: The image ID

    Returns:
        True if deleted, False if not found
    """
    directory = get_image_directory(image_id)

    if not directory.exists():
        return False

    # Remove the entire directory for this image
    shutil.rmtree(directory)
    return True


async def get_file_path(image_id: str, filename: str) -> Optional[Path]:
    """
    Get the full path to a file.

    Args:
        image_id: The image ID
        filename: The filename

    Returns:
        The full path or None if not found
    """
    file_path = get_image_directory(image_id) / filename

    if not file_path.exists():
        return None

    return file_path


def get_extension(filename: str) -> str:
    """Get the lowercase file extension without the dot."""
    return Path(filename).suffix.lower().lstrip(".")


def generate_stored_filename(original_filename: str) -> str:
    """Generate a safe stored filename from the original."""
    ext = get_extension(original_filename)
    return f"original.{ext}" if ext else "original"


def get_thumbnail_filename() -> str:
    """Get the standard thumbnail filename."""
    return "thumbnail.jpg"
