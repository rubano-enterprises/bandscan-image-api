#!/usr/bin/env python3
"""
Migration script to move operational data from Google Sheets to BandScan API.

This script:
1. Reads the Master spreadsheet to get all school configurations
2. For each school:
   - Populates the schools table with config from columns K, N
   - Populates school_sheets table with IDs from columns P, Q, R, S, T
   - Populates students table with UID and codes from student list columns B, I
   - Populates student_requests table from Column J JSON

Usage:
    python migrate_from_sheets.py [--dry-run]

Environment variables required:
    - GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE
    - DATABASE_PATH (defaults to ./data/bandscan.db)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Master spreadsheet ID from constants.dart
MASTER_SPREADSHEET_ID = '1n5NOs5DTHTc3sMbwFWB6gFHQg2CqYlwk0nksEQyFCcU'

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def get_credentials():
    """Get Google service account credentials."""
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_str:
        info = json.loads(json_str)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    file_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if file_path:
        return service_account.Credentials.from_service_account_file(file_path, scopes=SCOPES)

    raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE")


def get_sheets_service():
    """Get Google Sheets API service."""
    credentials = get_credentials()
    return build("sheets", "v4", credentials=credentials)


def get_cell_value(rows: List[List[str]], row: int, col: int) -> str:
    """Safely get a cell value from a 2D array."""
    if row < len(rows):
        r = rows[row]
        if col < len(r):
            return r[col].strip() if r[col] else ""
    return ""


def get_all_band_ids(service) -> List[Dict[str, str]]:
    """
    Read Master!A:B to get all band IDs and their student list spreadsheet IDs.
    Returns list of {band_id, student_list_spreadsheet_id}.
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=MASTER_SPREADSHEET_ID,
        range="Master!A:B"
    ).execute()

    rows = result.get("values", [])
    schools = []

    for row in rows:
        if len(row) >= 2:
            band_id = row[0].strip() if row[0] else ""
            spreadsheet_id = row[1].strip() if row[1] else ""
            if band_id and spreadsheet_id and band_id != "bandId":  # Skip header
                schools.append({
                    "band_id": band_id,
                    "student_list_spreadsheet_id": spreadsheet_id
                })

    return schools


def get_school_config(service, band_id: str) -> Dict[str, Any]:
    """
    Read school configuration from Master!{bandId}!K:T.

    Columns:
    - K1: Logo URL
    - K2: School name (short)
    - K3: Primary color hex
    - K4: Full school name
    - K5: Admin emails (comma-separated)
    - N1: Attendance template ID
    - P2:P200: Attendance sheet IDs
    - Q2:Q200: Check-in sheet IDs
    - R2:R200: Bus sheet IDs
    - S2:S200: Active bus sheet IDs
    - T2: Inventory sheet ID
    """
    try:
        # Read K column for basic config
        k_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!K1:K5"
        ).execute()
        k_rows = k_result.get("values", [])

        # Read N1 for attendance template
        n_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!N1"
        ).execute()
        n_rows = n_result.get("values", [])

        # Read P for attendance sheets
        p_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!P2:P200"
        ).execute()
        p_rows = p_result.get("values", [])

        # Read Q for check-in sheets
        q_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!Q2:Q200"
        ).execute()
        q_rows = q_result.get("values", [])

        # Read R:S for bus sheets and active status
        rs_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!R2:S200"
        ).execute()
        rs_rows = rs_result.get("values", [])

        # Read T2 for inventory sheet
        t_result = service.spreadsheets().values().get(
            spreadsheetId=MASTER_SPREADSHEET_ID,
            range=f"{band_id}!T2"
        ).execute()
        t_rows = t_result.get("values", [])

        # Extract values
        config = {
            "logo_url": get_cell_value(k_rows, 0, 0),
            "short_name": get_cell_value(k_rows, 1, 0) or band_id,
            "primary_color": get_cell_value(k_rows, 2, 0),
            "full_name": get_cell_value(k_rows, 3, 0),
            "admin_emails": get_cell_value(k_rows, 4, 0),
            "attendance_template_id": get_cell_value(n_rows, 0, 0) if n_rows else "",
            "inventory_sheet_id": get_cell_value(t_rows, 0, 0) if t_rows else "",
            "attendance_sheets": [],
            "checkin_sheets": [],
            "bus_sheets": [],
        }

        # Extract attendance sheets
        for row in p_rows:
            if row and row[0].strip():
                config["attendance_sheets"].append(row[0].strip())

        # Extract check-in sheets
        for row in q_rows:
            if row and row[0].strip():
                config["checkin_sheets"].append(row[0].strip())

        # Extract bus sheets with active status
        for row in rs_rows:
            if row and len(row) > 0 and row[0].strip():
                sheet_id = row[0].strip()
                is_active = len(row) > 1 and row[1].strip() == sheet_id
                config["bus_sheets"].append({
                    "sheet_id": sheet_id,
                    "is_active": is_active
                })

        return config

    except Exception as e:
        logger.error(f"Error reading config for {band_id}: {e}")
        return {}


def get_students_data(service, spreadsheet_id: str, sheet_name: str = "FullBand") -> List[Dict[str, Any]]:
    """
    Read student data from student list spreadsheet.

    Columns:
    - A: Name
    - B: UID (NFC tag)
    - C: Instrument
    - I: Student Code (6-char auth code)
    - J: Requests JSON
    """
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:J"
        ).execute()

        rows = result.get("values", [])
        students = []

        for i, row in enumerate(rows):
            if i == 0:  # Skip header
                continue

            # Pad row to ensure we have all columns
            while len(row) < 10:
                row.append("")

            name = row[0].strip() if row[0] else ""
            if not name:
                continue

            uid = row[1].strip() if len(row) > 1 and row[1] else None
            student_code = row[8].strip() if len(row) > 8 and row[8] else None
            requests_json = row[9].strip() if len(row) > 9 and row[9] else ""

            # Parse requests JSON
            requests = []
            if requests_json:
                try:
                    requests = json.loads(requests_json)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in requests for {name}: {requests_json[:50]}...")

            students.append({
                "name": name,
                "uid": uid if uid else None,
                "student_code": student_code if student_code else None,
                "requests": requests
            })

        return students

    except Exception as e:
        logger.error(f"Error reading students from {spreadsheet_id}: {e}")
        return []


async def migrate_school(
    band_id: str,
    student_list_spreadsheet_id: str,
    service,
    dry_run: bool = False
) -> Dict[str, int]:
    """Migrate a single school's data to the API database."""
    from app.database import (
        upsert_school,
        add_school_sheet,
        upsert_student,
        create_student_request,
    )
    from uuid import uuid4

    stats = {
        "sheets": 0,
        "students": 0,
        "requests": 0
    }

    logger.info(f"Migrating school: {band_id}")

    # Get school configuration
    config = get_school_config(service, band_id)
    if not config:
        logger.error(f"Could not get config for {band_id}, skipping")
        return stats

    # Get active student list from FullBand!M2 (if it exists)
    try:
        m_result = service.spreadsheets().values().get(
            spreadsheetId=student_list_spreadsheet_id,
            range="FullBand!M2"
        ).execute()
        m_rows = m_result.get("values", [])
        active_student_list = m_rows[0][0].strip() if m_rows and m_rows[0] else "FullBand"
    except Exception:
        active_student_list = "FullBand"

    if dry_run:
        logger.info(f"  [DRY RUN] Would create school: {band_id}")
        logger.info(f"    - short_name: {config.get('short_name')}")
        logger.info(f"    - full_name: {config.get('full_name')}")
        logger.info(f"    - active_student_list: {active_student_list}")
    else:
        # Create school record
        await upsert_school(
            band_id=band_id,
            student_list_spreadsheet_id=student_list_spreadsheet_id,
            short_name=config.get("short_name") or band_id,
            logo_url=config.get("logo_url") or None,
            primary_color=config.get("primary_color") or None,
            full_name=config.get("full_name") or None,
            admin_emails=config.get("admin_emails") or None,
            attendance_template_id=config.get("attendance_template_id") or None,
            inventory_sheet_id=config.get("inventory_sheet_id") or None,
            active_student_list=active_student_list,
        )
        logger.info(f"  Created school record")

    # Add attendance sheets
    for i, sheet_id in enumerate(config.get("attendance_sheets", [])):
        if dry_run:
            logger.info(f"  [DRY RUN] Would add attendance sheet: {sheet_id}")
        else:
            await add_school_sheet(band_id, "attendance", sheet_id, display_order=i)
        stats["sheets"] += 1

    # Add check-in sheets
    for i, sheet_id in enumerate(config.get("checkin_sheets", [])):
        if dry_run:
            logger.info(f"  [DRY RUN] Would add checkin sheet: {sheet_id}")
        else:
            await add_school_sheet(band_id, "checkin", sheet_id, display_order=i)
        stats["sheets"] += 1

    # Add bus sheets
    for i, bus_sheet in enumerate(config.get("bus_sheets", [])):
        if dry_run:
            logger.info(f"  [DRY RUN] Would add bus sheet: {bus_sheet['sheet_id']} (active={bus_sheet['is_active']})")
        else:
            await add_school_sheet(
                band_id,
                "bus",
                bus_sheet["sheet_id"],
                is_active=bus_sheet["is_active"],
                display_order=i
            )
        stats["sheets"] += 1

    # Get and migrate students
    students = get_students_data(service, student_list_spreadsheet_id, active_student_list)
    logger.info(f"  Found {len(students)} students")

    for student in students:
        if dry_run:
            if student["uid"] or student["student_code"]:
                logger.info(f"  [DRY RUN] Would create student: {student['name']} (uid={student['uid']}, code={student['student_code']})")
        else:
            # Only create student record if they have UID or code
            if student["uid"] or student["student_code"]:
                await upsert_student(
                    band_id=band_id,
                    name=student["name"],
                    uid=student["uid"],
                    student_code=student["student_code"],
                )
                stats["students"] += 1

        # Migrate requests
        for req in student.get("requests", []):
            if req.get("status") == "pending":
                if dry_run:
                    logger.info(f"  [DRY RUN] Would create request: {req.get('type')} for {student['name']}")
                else:
                    await create_student_request(
                        request_id=req.get("id") or str(uuid4()),
                        band_id=band_id,
                        student_name=student["name"],
                        request_type=req.get("type"),
                        new_value=req.get("newValue", ""),
                    )
                stats["requests"] += 1

    logger.info(f"  Migrated {stats['sheets']} sheets, {stats['students']} students, {stats['requests']} pending requests")

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Migrate data from Google Sheets to BandScan API")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without making changes")
    parser.add_argument("--band-id", help="Migrate only a specific school (by band ID)")
    args = parser.parse_args()

    logger.info("Starting migration from Google Sheets to BandScan API")
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Initialize database (only if not dry run)
    if not args.dry_run:
        from app.database import init_database
        await init_database()
        logger.info("Database initialized")

    # Get Sheets service
    service = get_sheets_service()

    # Get all schools
    schools = get_all_band_ids(service)
    logger.info(f"Found {len(schools)} schools in Master spreadsheet")

    # Filter to specific school if requested
    if args.band_id:
        schools = [s for s in schools if s["band_id"] == args.band_id]
        if not schools:
            logger.error(f"School '{args.band_id}' not found in Master spreadsheet")
            return

    # Migrate each school
    total_stats = {"sheets": 0, "students": 0, "requests": 0}

    for school in schools:
        try:
            stats = await migrate_school(
                band_id=school["band_id"],
                student_list_spreadsheet_id=school["student_list_spreadsheet_id"],
                service=service,
                dry_run=args.dry_run,
            )
            for key in total_stats:
                total_stats[key] += stats[key]
        except Exception as e:
            logger.error(f"Error migrating school {school['band_id']}: {e}")

    logger.info("=" * 50)
    logger.info("Migration complete!")
    logger.info(f"Total: {len(schools)} schools, {total_stats['sheets']} sheets, "
                f"{total_stats['students']} students, {total_stats['requests']} pending requests")


if __name__ == "__main__":
    asyncio.run(main())
