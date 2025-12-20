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

# Column indices for student list (0-indexed)
COL_NAME = 0  # A
COL_UID = 1   # B
COL_INSTRUMENT = 2  # C
COL_STUDENT_CODE = 8  # I
COL_REQUESTS = 9  # J

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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
