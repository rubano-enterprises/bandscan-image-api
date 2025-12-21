"""Google Sheets service for student requests."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from google.oauth2 import service_account
from googleapiclient.discovery import build

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Column indices for student list (0-indexed) - legacy fallbacks
COL_NAME = 0  # A
COL_UID = 1   # B
COL_INSTRUMENT = 2  # C
COL_STUDENT_CODE = 8  # I
COL_REQUESTS = 9  # J

# Scopes for Sheets API and Drive API (for modified time check)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def get_credentials():
    """Get Google service account credentials."""
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    elif settings.google_service_account_file:
        return service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=SCOPES
        )
    return None


def get_sheets_service():
    """Get Google Sheets API service."""
    credentials = get_credentials()
    if not credentials:
        raise ValueError("Google Sheets credentials not configured")
    return build("sheets", "v4", credentials=credentials)


def get_drive_service():
    """Get Google Drive API service (for file metadata)."""
    credentials = get_credentials()
    if not credentials:
        raise ValueError("Google Drive credentials not configured")
    return build("drive", "v3", credentials=credentials)


async def get_spreadsheet_modified_time(spreadsheet_id: str) -> Optional[str]:
    """
    Get the last modified time of a spreadsheet.
    Returns ISO format string or None if not found.
    """
    try:
        service = get_drive_service()
        result = service.files().get(
            fileId=spreadsheet_id,
            fields="modifiedTime"
        ).execute()
        return result.get("modifiedTime")
    except Exception as e:
        logger.error(f"Error getting spreadsheet modified time: {e}")
        return None


def parse_header_columns(header_row: list) -> dict:
    """
    Parse header row to find column indices for each field.
    Returns dict mapping field name to column index.
    Handles various naming conventions.
    """
    column_map = {}
    header_lower = [h.lower().strip() if h else "" for h in header_row]

    # Name column - typically first column
    for i, h in enumerate(header_lower):
        if h in ("name", "student name", "full name", "student"):
            column_map["name"] = i
            break
    if "name" not in column_map and header_row:
        column_map["name"] = 0  # Default to first column

    # Instrument column
    for i, h in enumerate(header_lower):
        if h in ("instrument", "instruments", "section", "part"):
            column_map["instrument"] = i
            break

    # UID column (NFC tag)
    for i, h in enumerate(header_lower):
        if h in ("uid", "nfc", "nfc uid", "tag", "tag uid", "nfc tag"):
            column_map["uid"] = i
            break

    # Student code column
    for i, h in enumerate(header_lower):
        if h in ("code", "student code", "auth code", "qr", "qr code", "login code"):
            column_map["student_code"] = i
            break

    logger.debug(f"Parsed column map: {column_map}")
    return column_map


async def find_student_row(
    spreadsheet_id: str,
    sheet_name: str,
    student_code: Optional[str] = None,
    student_uid: Optional[str] = None,
) -> Optional[int]:
    """
    Find the row number for a student by code or UID.
    Returns 1-indexed row number or None if not found.
    """
    service = get_sheets_service()

    # Read all student data (columns A-J)
    range_name = f"{sheet_name}!A:J"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()

    rows = result.get("values", [])

    for i, row in enumerate(rows):
        if i == 0:  # Skip header row
            continue

        # Pad row to have enough columns
        while len(row) < 10:
            row.append("")

        row_uid = row[COL_UID] if len(row) > COL_UID else ""
        row_code = row[COL_STUDENT_CODE] if len(row) > COL_STUDENT_CODE else ""

        # Match by UID first, then by code
        if student_uid and row_uid == student_uid:
            return i + 1  # 1-indexed
        if student_code and row_code == student_code:
            return i + 1  # 1-indexed

    return None


async def get_student_requests(
    spreadsheet_id: str,
    sheet_name: str,
    student_code: Optional[str] = None,
    student_uid: Optional[str] = None,
) -> list:
    """Get current requests for a student."""
    row = await find_student_row(spreadsheet_id, sheet_name, student_code, student_uid)
    if not row:
        return []

    service = get_sheets_service()
    range_name = f"{sheet_name}!J{row}"

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()

    values = result.get("values", [[]])
    requests_json = values[0][0] if values and values[0] else ""

    if not requests_json:
        return []

    try:
        return json.loads(requests_json)
    except json.JSONDecodeError:
        return []


async def add_student_request(
    spreadsheet_id: str,
    sheet_name: str,
    request_type: str,
    new_value: str,
    student_code: Optional[str] = None,
    student_uid: Optional[str] = None,
    request_id: Optional[str] = None,
    request_timestamp: Optional[str] = None,
) -> dict:
    """
    Add a new request for a student.
    Returns the created request.
    """
    row = await find_student_row(spreadsheet_id, sheet_name, student_code, student_uid)
    if not row:
        raise ValueError("Student not found")

    # Get existing requests
    existing_requests = await get_student_requests(
        spreadsheet_id, sheet_name, student_code, student_uid
    )

    # Check for duplicate pending request of same type
    for req in existing_requests:
        if req.get("type") == request_type and req.get("status") == "pending":
            raise ValueError(f"Already have a pending {request_type} request")

    # Create new request
    new_request = {
        "id": request_id or str(uuid4()),
        "type": request_type,
        "newValue": new_value,
        "timestamp": request_timestamp or datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }

    # Add to existing requests
    existing_requests.append(new_request)

    # Write back to sheet
    service = get_sheets_service()
    range_name = f"{sheet_name}!J{row}"

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[json.dumps(existing_requests)]]},
    ).execute()

    logger.info(f"Added request {new_request['id']} for student at row {row}")

    return new_request


async def update_student_uid(
    spreadsheet_id: str,
    sheet_name: str,
    student_code: str,
    new_uid: str,
) -> bool:
    """
    Update a student's UID (for tag claiming).
    Returns True if successful.
    """
    row = await find_student_row(spreadsheet_id, sheet_name, student_code=student_code)
    if not row:
        raise ValueError("Student not found")

    service = get_sheets_service()
    range_name = f"{sheet_name}!B{row}"

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[new_uid]]},
    ).execute()

    logger.info(f"Updated UID for student at row {row}")

    return True


async def verify_uid_available(
    spreadsheet_id: str,
    sheet_name: str,
    uid: str,
) -> bool:
    """Check if a UID is available (not already assigned to another student)."""
    service = get_sheets_service()

    # Read all UIDs
    range_name = f"{sheet_name}!B:B"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()

    rows = result.get("values", [])

    for i, row in enumerate(rows):
        if i == 0:  # Skip header
            continue
        if row and row[0] == uid:
            return False  # UID already in use

    return True


async def find_student_row_by_name(
    spreadsheet_id: str,
    sheet_name: str,
    student_name: str,
) -> Optional[int]:
    """
    Find the row number for a student by name.
    Returns 1-indexed row number or None if not found.
    """
    service = get_sheets_service()

    # Read all names (Column A)
    range_name = f"{sheet_name}!A:A"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()

    rows = result.get("values", [])

    for i, row in enumerate(rows):
        if i == 0:  # Skip header row
            continue
        if row and row[0] == student_name:
            return i + 1  # 1-indexed

    return None


async def update_student_name(
    spreadsheet_id: str,
    sheet_name: str,
    old_name: str,
    new_name: str,
) -> bool:
    """
    Update a student's name in the Sheet (Column A).
    Used when approving nameChange requests.
    Returns True if successful.
    """
    row = await find_student_row_by_name(spreadsheet_id, sheet_name, old_name)
    if not row:
        raise ValueError(f"Student '{old_name}' not found in sheet")

    service = get_sheets_service()
    range_name = f"{sheet_name}!A{row}"

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[new_name]]},
    ).execute()

    logger.info(f"Updated name in sheet row {row}: {old_name} -> {new_name}")

    return True


async def update_student_instrument(
    spreadsheet_id: str,
    sheet_name: str,
    student_name: str,
    new_instrument: str,
) -> bool:
    """
    Update a student's instrument in the Sheet (Column B after migration).
    Used when approving instrumentChange requests.
    Returns True if successful.

    Note: After migration, column layout is:
    - A: Name
    - B: Instrument (was C before migration)
    """
    row = await find_student_row_by_name(spreadsheet_id, sheet_name, student_name)
    if not row:
        raise ValueError(f"Student '{student_name}' not found in sheet")

    service = get_sheets_service()
    # Post-migration: instrument is in Column B
    # Pre-migration: instrument is in Column C
    # For now, use Column C (current layout), can be updated during migration
    range_name = f"{sheet_name}!C{row}"

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[new_instrument]]},
    ).execute()

    logger.info(f"Updated instrument for {student_name} at row {row}: {new_instrument}")

    return True


async def get_all_students_from_sheet(
    spreadsheet_id: str,
    sheet_name: str,
) -> list[dict]:
    """
    Get all students from a Google Sheet.
    Parses column headers dynamically to find name, instrument, uid, and student_code.
    Returns list of dicts with name, instrument, uid, and student_code.
    """
    service = get_sheets_service()

    # Read columns A through C (covers name, instrument, and possible UID in old format)
    # This is a lightweight read - we don't need all columns
    range_name = f"{sheet_name}!A:C"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()

    rows = result.get("values", [])
    students = []

    if not rows:
        logger.warning(f"No data found in sheet {sheet_name}")
        return students

    # Parse header row to find column indices
    header_row = rows[0] if rows else []
    column_map = parse_header_columns(header_row)

    name_col = column_map.get("name", 0)
    instrument_col = column_map.get("instrument")
    uid_col = column_map.get("uid")

    for i, row in enumerate(rows):
        if i == 0:  # Skip header row
            continue

        # Pad row if needed
        while len(row) <= max(name_col, instrument_col or 0, uid_col or 0):
            row.append("")

        name = row[name_col].strip() if len(row) > name_col and row[name_col] else ""
        instrument = None
        uid = None

        if instrument_col is not None and len(row) > instrument_col:
            instrument = row[instrument_col].strip() if row[instrument_col] else None

        if uid_col is not None and len(row) > uid_col:
            uid = row[uid_col].strip() if row[uid_col] else None

        if name:  # Only include rows with names
            students.append({
                "name": name,
                "instrument": instrument if instrument else None,
                "uid": uid if uid else None,
                "student_code": None,  # Codes are stored in API only now
            })

    logger.info(f"Found {len(students)} students in sheet {sheet_name} (columns: {column_map})")
    return students
