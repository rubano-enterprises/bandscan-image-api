"""SQLite database operations for image metadata."""

import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

from .config import get_settings

settings = get_settings()

# SQL for creating the images table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    width INTEGER,
    height INTEGER,
    thumbnail_filename TEXT,
    display_order INTEGER DEFAULT 0,
    is_primary INTEGER DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_images_item_id ON images(item_id);
CREATE INDEX IF NOT EXISTS idx_images_item_order ON images(item_id, display_order);
"""

# SQL for creating the student requests queue table
CREATE_REQUESTS_QUEUE_SQL = """
CREATE TABLE IF NOT EXISTS student_requests_queue (
    id TEXT PRIMARY KEY,
    spreadsheet_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    request_type TEXT NOT NULL,
    student_code TEXT,
    student_uid TEXT,
    new_value TEXT NOT NULL,
    request_timestamp TEXT NOT NULL,
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    processed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON student_requests_queue(status);
CREATE INDEX IF NOT EXISTS idx_requests_queued ON student_requests_queue(queued_at);
"""

# SQL for device tokens table
CREATE_DEVICE_TOKENS_SQL = """
CREATE TABLE IF NOT EXISTS device_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_uid TEXT NOT NULL,
    band_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tokens_student ON device_tokens(student_uid, band_id);
CREATE INDEX IF NOT EXISTS idx_tokens_band ON device_tokens(band_id);
CREATE INDEX IF NOT EXISTS idx_tokens_token ON device_tokens(token);
"""

# SQL for notifications table
CREATE_NOTIFICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    band_id TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    recipient_uids TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    fcm_response TEXT,
    apns_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_band ON notifications(band_id);
CREATE INDEX IF NOT EXISTS idx_notifications_sent ON notifications(sent_at);
"""

# Migration to add is_primary column if it doesn't exist
MIGRATION_ADD_IS_PRIMARY = """
ALTER TABLE images ADD COLUMN is_primary INTEGER DEFAULT 0;
"""


async def init_database():
    """Initialize the database and create tables if needed."""
    # Ensure database directory exists
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(CREATE_TABLE_SQL)
        await db.executescript(CREATE_REQUESTS_QUEUE_SQL)
        await db.executescript(CREATE_DEVICE_TOKENS_SQL)
        await db.executescript(CREATE_NOTIFICATIONS_SQL)
        await db.commit()

        # Run migrations for existing databases
        try:
            await db.execute(MIGRATION_ADD_IS_PRIMARY)
            await db.commit()
        except Exception:
            # Column already exists
            pass


@asynccontextmanager
async def get_db():
    """Get a database connection context manager."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def insert_image(
    image_id: str,
    item_id: str,
    filename: str,
    stored_filename: str,
    content_type: str,
    size_bytes: int,
    width: Optional[int] = None,
    height: Optional[int] = None,
    thumbnail_filename: Optional[str] = None,
    display_order: int = 0,
    is_primary: bool = False,
    description: Optional[str] = None,
) -> dict:
    """Insert a new image record."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO images (
                id, item_id, filename, stored_filename, content_type,
                size_bytes, width, height, thumbnail_filename,
                display_order, is_primary, description, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id, item_id, filename, stored_filename, content_type,
                size_bytes, width, height, thumbnail_filename,
                display_order, 1 if is_primary else 0, description, now, now
            )
        )
        await db.commit()

    return await get_image_by_id(image_id)


async def get_image_by_id(image_id: str) -> Optional[dict]:
    """Get an image by its ID."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM images WHERE id = ?",
            (image_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_images_for_item(item_id: str) -> List[dict]:
    """Get all images for an inventory item, ordered by display_order."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM images WHERE item_id = ? ORDER BY display_order ASC",
            (item_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_max_order_for_item(item_id: str) -> int:
    """Get the maximum display order for an item's images."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT MAX(display_order) as max_order FROM images WHERE item_id = ?",
            (item_id,)
        )
        row = await cursor.fetchone()
        if row and row["max_order"] is not None:
            return row["max_order"]
        return -1


async def update_image(
    image_id: str,
    display_order: Optional[int] = None,
    description: Optional[str] = None,
) -> Optional[dict]:
    """Update an image's metadata."""
    async with get_db() as db:
        updates = []
        params = []

        if display_order is not None:
            updates.append("display_order = ?")
            params.append(display_order)

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            return await get_image_by_id(image_id)

        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(image_id)

        await db.execute(
            f"UPDATE images SET {', '.join(updates)} WHERE id = ?",
            params
        )
        await db.commit()

    return await get_image_by_id(image_id)


async def update_image_orders(item_id: str, image_ids: List[str]) -> bool:
    """Update the display order of images based on the provided list order."""
    async with get_db() as db:
        for order, image_id in enumerate(image_ids):
            await db.execute(
                "UPDATE images SET display_order = ?, updated_at = ? WHERE id = ? AND item_id = ?",
                (order, datetime.utcnow().isoformat(), image_id, item_id)
            )
        await db.commit()
    return True


async def delete_image(image_id: str) -> Optional[dict]:
    """Delete an image and return its data (for file cleanup)."""
    image = await get_image_by_id(image_id)
    if image:
        async with get_db() as db:
            await db.execute("DELETE FROM images WHERE id = ?", (image_id,))
            await db.commit()
    return image


async def delete_images_for_item(item_id: str) -> List[dict]:
    """Delete all images for an item and return their data (for file cleanup)."""
    images = await get_images_for_item(item_id)
    if images:
        async with get_db() as db:
            await db.execute("DELETE FROM images WHERE item_id = ?", (item_id,))
            await db.commit()
    return images


async def set_primary_image(item_id: str, image_id: str) -> bool:
    """Set an image as the primary image for an item (unsets others)."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        # First, unset all primary flags for this item
        await db.execute(
            "UPDATE images SET is_primary = 0, updated_at = ? WHERE item_id = ?",
            (now, item_id)
        )
        # Then set the specified image as primary
        await db.execute(
            "UPDATE images SET is_primary = 1, updated_at = ? WHERE id = ? AND item_id = ?",
            (now, image_id, item_id)
        )
        await db.commit()
    return True


async def get_primary_image_for_item(item_id: str) -> Optional[dict]:
    """Get the primary image for an item, or the first image if none is set as primary."""
    async with get_db() as db:
        # First try to get the primary image
        cursor = await db.execute(
            "SELECT * FROM images WHERE item_id = ? AND is_primary = 1 LIMIT 1",
            (item_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)

        # Fall back to first image by display order
        cursor = await db.execute(
            "SELECT * FROM images WHERE item_id = ? ORDER BY display_order ASC LIMIT 1",
            (item_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)

        return None


# Student requests queue operations

async def queue_student_request(
    request_id: str,
    spreadsheet_id: str,
    sheet_name: str,
    request_type: str,
    new_value: str,
    request_timestamp: str,
    student_code: Optional[str] = None,
    student_uid: Optional[str] = None,
) -> dict:
    """Add a student request to the queue.

    Args:
        request_timestamp: The original timestamp when the student made the request.
                          This is preserved and written to Google Sheets.
    """
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO student_requests_queue (
                id, spreadsheet_id, sheet_name, request_type,
                student_code, student_uid, new_value, request_timestamp,
                queued_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (request_id, spreadsheet_id, sheet_name, request_type,
             student_code, student_uid, new_value, request_timestamp, now)
        )
        await db.commit()

    return {
        "id": request_id,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "request_type": request_type,
        "student_code": student_code,
        "student_uid": student_uid,
        "new_value": new_value,
        "request_timestamp": request_timestamp,
        "queued_at": now,
        "status": "pending",
    }


async def get_pending_requests(limit: int = 10) -> List[dict]:
    """Get pending requests from the queue, oldest first by queue position."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM student_requests_queue
            WHERE status = 'pending'
            ORDER BY queued_at ASC
            LIMIT ?
            """,
            (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def mark_request_processed(request_id: str) -> None:
    """Mark a request as successfully processed."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            UPDATE student_requests_queue
            SET status = 'processed', processed_at = ?
            WHERE id = ?
            """,
            (now, request_id)
        )
        await db.commit()


async def mark_request_failed(request_id: str, error: str) -> None:
    """Mark a request as failed and move it to the end of the queue.

    The request stays pending but gets a new queued_at time so other items
    can process first. The original request_timestamp is preserved.
    No data is ever lost.
    """
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            UPDATE student_requests_queue
            SET retry_count = retry_count + 1,
                last_error = ?,
                queued_at = ?
            WHERE id = ?
            """,
            (error, now, request_id)
        )
        await db.commit()


async def get_queue_stats() -> dict:
    """Get queue statistics."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM student_requests_queue
            GROUP BY status
            """
        )
        rows = await cursor.fetchall()
        stats = {row["status"]: row["count"] for row in rows}
        return {
            "pending": stats.get("pending", 0),
            "processed": stats.get("processed", 0),
            "failed": stats.get("failed", 0),
        }


# Device token operations

async def upsert_device_token(
    student_uid: str,
    band_id: str,
    token: str,
    platform: str,
) -> dict:
    """Insert or update a device token for a student."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        # Delete any existing token for this device token (handles device changes)
        await db.execute("DELETE FROM device_tokens WHERE token = ?", (token,))
        # Delete any existing tokens for this student/band (one device per student)
        await db.execute(
            "DELETE FROM device_tokens WHERE student_uid = ? AND band_id = ?",
            (student_uid, band_id)
        )
        # Insert the new token
        await db.execute(
            """
            INSERT INTO device_tokens (student_uid, band_id, token, platform, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_uid, band_id, token, platform, now, now)
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM device_tokens WHERE token = ?",
            (token,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_device_tokens_for_students(
    student_uids: List[str],
    band_id: str
) -> List[dict]:
    """Get device tokens for a list of students."""
    async with get_db() as db:
        placeholders = ",".join("?" * len(student_uids))
        cursor = await db.execute(
            f"""
            SELECT * FROM device_tokens
            WHERE student_uid IN ({placeholders})
            AND band_id = ?
            ORDER BY last_seen DESC
            """,
            (*student_uids, band_id)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_token_last_seen(token: str) -> None:
    """Update the last_seen timestamp for a device token."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "UPDATE device_tokens SET last_seen = ? WHERE token = ?",
            (now, token)
        )
        await db.commit()


async def delete_device_token(token: str) -> bool:
    """Delete a device token."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM device_tokens WHERE token = ?",
            (token,)
        )
        await db.commit()
        return cursor.rowcount > 0


# Notification operations

async def insert_notification(
    notification_id: str,
    band_id: str,
    sender_email: str,
    title: str,
    body: str,
    recipient_uids: List[str],
    success_count: int = 0,
    failure_count: int = 0,
    fcm_response: Optional[str] = None,
    apns_response: Optional[str] = None,
) -> dict:
    """Insert a notification record."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        recipient_uids_str = ",".join(recipient_uids)
        await db.execute(
            """
            INSERT INTO notifications (
                id, band_id, sender_email, title, body, recipient_uids,
                sent_at, success_count, failure_count, fcm_response, apns_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (notification_id, band_id, sender_email, title, body, recipient_uids_str,
             now, success_count, failure_count, fcm_response, apns_response)
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_notifications_for_band(
    band_id: str,
    limit: int = 50,
    offset: int = 0
) -> List[dict]:
    """Get recent notifications for a band."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM notifications
            WHERE band_id = ?
            ORDER BY sent_at DESC
            LIMIT ? OFFSET ?
            """,
            (band_id, limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_notification_by_id(notification_id: str) -> Optional[dict]:
    """Get a notification by ID."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
