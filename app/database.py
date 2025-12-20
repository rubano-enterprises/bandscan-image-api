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

# SQL for schools table (replaces Master spreadsheet)
CREATE_SCHOOLS_SQL = """
CREATE TABLE IF NOT EXISTS schools (
    band_id TEXT PRIMARY KEY,
    student_list_spreadsheet_id TEXT NOT NULL,
    logo_url TEXT,
    short_name TEXT NOT NULL,
    primary_color TEXT,
    full_name TEXT,
    admin_emails TEXT,
    attendance_template_id TEXT,
    inventory_sheet_id TEXT,
    active_student_list TEXT DEFAULT 'FullBand',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# SQL for school sheet mappings (replaces columns P, Q, R, S in Master)
CREATE_SCHOOL_SHEETS_SQL = """
CREATE TABLE IF NOT EXISTS school_sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id TEXT NOT NULL,
    sheet_type TEXT NOT NULL,
    sheet_id TEXT NOT NULL,
    is_active INTEGER DEFAULT 0,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(band_id, sheet_type, sheet_id)
);

CREATE INDEX IF NOT EXISTS idx_school_sheets_band ON school_sheets(band_id);
CREATE INDEX IF NOT EXISTS idx_school_sheets_type ON school_sheets(band_id, sheet_type);
"""

# SQL for students table (UID and auth code storage, linked by name)
CREATE_STUDENTS_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id TEXT NOT NULL,
    name TEXT NOT NULL,
    uid TEXT,
    student_code TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(band_id, name)
);

CREATE INDEX IF NOT EXISTS idx_students_uid ON students(uid);
CREATE INDEX IF NOT EXISTS idx_students_code ON students(student_code);
CREATE INDEX IF NOT EXISTS idx_students_band_name ON students(band_id, name);
"""

# SQL for student requests table (replaces Column J JSON)
CREATE_STUDENT_REQUESTS_SQL = """
CREATE TABLE IF NOT EXISTS student_requests (
    id TEXT PRIMARY KEY,
    band_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    request_type TEXT NOT NULL,
    new_value TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    admin_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_student_requests_band ON student_requests(band_id);
CREATE INDEX IF NOT EXISTS idx_student_requests_status ON student_requests(status);
CREATE INDEX IF NOT EXISTS idx_student_requests_student ON student_requests(band_id, student_name);
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
        await db.executescript(CREATE_SCHOOLS_SQL)
        await db.executescript(CREATE_SCHOOL_SHEETS_SQL)
        await db.executescript(CREATE_STUDENTS_SQL)
        await db.executescript(CREATE_STUDENT_REQUESTS_SQL)
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


# ============================================================================
# School operations
# ============================================================================

async def get_school(band_id: str) -> Optional[dict]:
    """Get a school by band_id."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM schools WHERE band_id = ?",
            (band_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_schools() -> List[dict]:
    """Get all schools."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM schools ORDER BY short_name")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def upsert_school(
    band_id: str,
    student_list_spreadsheet_id: str,
    short_name: str,
    logo_url: Optional[str] = None,
    primary_color: Optional[str] = None,
    full_name: Optional[str] = None,
    admin_emails: Optional[str] = None,
    attendance_template_id: Optional[str] = None,
    inventory_sheet_id: Optional[str] = None,
    active_student_list: str = "FullBand",
) -> dict:
    """Insert or update a school."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO schools (
                band_id, student_list_spreadsheet_id, logo_url, short_name,
                primary_color, full_name, admin_emails, attendance_template_id,
                inventory_sheet_id, active_student_list, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(band_id) DO UPDATE SET
                student_list_spreadsheet_id = excluded.student_list_spreadsheet_id,
                logo_url = excluded.logo_url,
                short_name = excluded.short_name,
                primary_color = excluded.primary_color,
                full_name = excluded.full_name,
                admin_emails = excluded.admin_emails,
                attendance_template_id = excluded.attendance_template_id,
                inventory_sheet_id = excluded.inventory_sheet_id,
                active_student_list = excluded.active_student_list,
                updated_at = excluded.updated_at
            """,
            (band_id, student_list_spreadsheet_id, logo_url, short_name,
             primary_color, full_name, admin_emails, attendance_template_id,
             inventory_sheet_id, active_student_list, now, now)
        )
        await db.commit()
    return await get_school(band_id)


async def update_school(band_id: str, **kwargs) -> Optional[dict]:
    """Update specific fields of a school."""
    allowed_fields = {
        'logo_url', 'short_name', 'primary_color', 'full_name',
        'admin_emails', 'attendance_template_id', 'inventory_sheet_id',
        'active_student_list', 'student_list_spreadsheet_id'
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return await get_school(band_id)

    async with get_db() as db:
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = ?"
        params = list(updates.values()) + [datetime.utcnow().isoformat(), band_id]
        await db.execute(
            f"UPDATE schools SET {set_clause} WHERE band_id = ?",
            params
        )
        await db.commit()
    return await get_school(band_id)


async def delete_school(band_id: str) -> bool:
    """Delete a school and all related data."""
    async with get_db() as db:
        # Delete related data first
        await db.execute("DELETE FROM school_sheets WHERE band_id = ?", (band_id,))
        await db.execute("DELETE FROM students WHERE band_id = ?", (band_id,))
        await db.execute("DELETE FROM student_requests WHERE band_id = ?", (band_id,))
        cursor = await db.execute("DELETE FROM schools WHERE band_id = ?", (band_id,))
        await db.commit()
        return cursor.rowcount > 0


# ============================================================================
# School sheets operations
# ============================================================================

async def get_school_sheets(band_id: str, sheet_type: str) -> List[dict]:
    """Get all sheets of a specific type for a school."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM school_sheets
            WHERE band_id = ? AND sheet_type = ?
            ORDER BY display_order, created_at
            """,
            (band_id, sheet_type)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_active_bus_sheets(band_id: str) -> List[str]:
    """Get active bus sheet IDs for a school."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT sheet_id FROM school_sheets
            WHERE band_id = ? AND sheet_type = 'bus' AND is_active = 1
            ORDER BY display_order
            """,
            (band_id,)
        )
        rows = await cursor.fetchall()
        return [row["sheet_id"] for row in rows]


async def add_school_sheet(
    band_id: str,
    sheet_type: str,
    sheet_id: str,
    is_active: bool = False,
    display_order: int = 0,
) -> dict:
    """Add a sheet to a school."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO school_sheets (band_id, sheet_type, sheet_id, is_active, display_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(band_id, sheet_type, sheet_id) DO UPDATE SET
                is_active = excluded.is_active,
                display_order = excluded.display_order
            """,
            (band_id, sheet_type, sheet_id, 1 if is_active else 0, display_order, now)
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM school_sheets WHERE band_id = ? AND sheet_type = ? AND sheet_id = ?",
            (band_id, sheet_type, sheet_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def remove_school_sheet(band_id: str, sheet_type: str, sheet_id: str) -> bool:
    """Remove a sheet from a school."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM school_sheets WHERE band_id = ? AND sheet_type = ? AND sheet_id = ?",
            (band_id, sheet_type, sheet_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def set_bus_sheet_active(band_id: str, sheet_id: str, is_active: bool) -> bool:
    """Set the active status of a bus sheet."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE school_sheets SET is_active = ?
            WHERE band_id = ? AND sheet_type = 'bus' AND sheet_id = ?
            """,
            (1 if is_active else 0, band_id, sheet_id)
        )
        await db.commit()
        return cursor.rowcount > 0


# ============================================================================
# Student operations (UID and auth code storage)
# ============================================================================

async def get_student_by_name(band_id: str, name: str) -> Optional[dict]:
    """Get a student by name."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM students WHERE band_id = ? AND name = ?",
            (band_id, name)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_student_by_uid(band_id: str, uid: str) -> Optional[dict]:
    """Get a student by NFC UID."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM students WHERE band_id = ? AND uid = ?",
            (band_id, uid)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_student_by_code(band_id: str, student_code: str) -> Optional[dict]:
    """Get a student by auth code."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM students WHERE band_id = ? AND student_code = ?",
            (band_id, student_code)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_students(band_id: str) -> List[dict]:
    """Get all students for a school."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM students WHERE band_id = ? ORDER BY name",
            (band_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def upsert_student(
    band_id: str,
    name: str,
    uid: Optional[str] = None,
    student_code: Optional[str] = None,
) -> dict:
    """Insert or update a student."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO students (band_id, name, uid, student_code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(band_id, name) DO UPDATE SET
                uid = COALESCE(excluded.uid, students.uid),
                student_code = COALESCE(excluded.student_code, students.student_code),
                updated_at = excluded.updated_at
            """,
            (band_id, name, uid, student_code, now, now)
        )
        await db.commit()
    return await get_student_by_name(band_id, name)


async def update_student(band_id: str, name: str, **kwargs) -> Optional[dict]:
    """Update specific fields of a student."""
    allowed_fields = {'uid', 'student_code'}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return await get_student_by_name(band_id, name)

    async with get_db() as db:
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = ?"
        params = list(updates.values()) + [datetime.utcnow().isoformat(), band_id, name]
        await db.execute(
            f"UPDATE students SET {set_clause} WHERE band_id = ? AND name = ?",
            params
        )
        await db.commit()
    return await get_student_by_name(band_id, name)


async def delete_student(band_id: str, name: str) -> bool:
    """Delete a student."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM students WHERE band_id = ? AND name = ?",
            (band_id, name)
        )
        await db.commit()
        return cursor.rowcount > 0


async def check_student_code_exists(student_code: str) -> bool:
    """Check if a student code already exists (globally unique)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM students WHERE student_code = ?",
            (student_code,)
        )
        row = await cursor.fetchone()
        return row is not None


# ============================================================================
# Student request operations
# ============================================================================

async def create_student_request(
    request_id: str,
    band_id: str,
    student_name: str,
    request_type: str,
    new_value: str,
) -> dict:
    """Create a new student request."""
    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            INSERT INTO student_requests (id, band_id, student_name, request_type, new_value, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (request_id, band_id, student_name, request_type, new_value, now)
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM student_requests WHERE id = ?",
            (request_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_student_request(request_id: str) -> Optional[dict]:
    """Get a student request by ID."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM student_requests WHERE id = ?",
            (request_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_student_requests(
    band_id: str,
    status: Optional[str] = None,
    request_type: Optional[str] = None,
    student_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    """Get student requests with optional filters."""
    async with get_db() as db:
        query = "SELECT * FROM student_requests WHERE band_id = ?"
        params = [band_id]

        if status:
            query += " AND status = ?"
            params.append(status)
        if request_type:
            query += " AND request_type = ?"
            params.append(request_type)
        if student_name:
            query += " AND student_name = ?"
            params.append(student_name)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def resolve_student_request(
    request_id: str,
    status: str,
    admin_response: Optional[str] = None,
) -> Optional[dict]:
    """Resolve a student request (approve or deny)."""
    if status not in ('approved', 'denied'):
        raise ValueError("Status must be 'approved' or 'denied'")

    async with get_db() as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """
            UPDATE student_requests
            SET status = ?, admin_response = ?, resolved_at = ?
            WHERE id = ?
            """,
            (status, admin_response, now, request_id)
        )
        await db.commit()
    return await get_student_request(request_id)


async def delete_student_request(request_id: str) -> bool:
    """Delete (cancel) a student request."""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM student_requests WHERE id = ?",
            (request_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
