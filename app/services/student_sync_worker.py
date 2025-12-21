"""Background worker for syncing students from Google Sheets."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from ..database import (
    get_all_schools,
    get_school,
    update_school,
    upsert_student,
    delete_students_not_in_list,
    get_all_students,
)
from . import sheets_service

logger = logging.getLogger(__name__)


class StudentSyncWorker:
    """Background worker that periodically syncs students from Google Sheets."""

    def __init__(self, poll_interval: float = 10.0):
        """
        Initialize the sync worker.

        Args:
            poll_interval: Seconds between sync checks (default 10 seconds)
        """
        self._poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background worker."""
        if self._running:
            logger.warning("Student sync worker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Student sync worker started")

    async def stop(self):
        """Stop the background worker gracefully."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Student sync worker stopped")

    async def _run(self):
        """Main worker loop."""
        # Initial delay to let the app start up
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._sync_all_schools()
            except Exception as e:
                logger.exception(f"Error in student sync worker loop: {e}")

            # Wait before next poll
            await asyncio.sleep(self._poll_interval)

    async def _sync_all_schools(self):
        """Check and sync all schools if their sheets have changed."""
        schools = await get_all_schools()

        for school in schools:
            try:
                await self._sync_school_if_changed(school)
            except Exception as e:
                logger.error(f"Error syncing school {school.get('band_id')}: {e}")

    async def _sync_school_if_changed(self, school: dict):
        """
        Check if a school's spreadsheet has changed and sync if needed.
        """
        band_id = school.get("band_id")
        spreadsheet_id = school.get("student_list_spreadsheet_id")
        active_list = school.get("active_student_list", "FullBand")
        last_sheet_modified = school.get("sheet_modified_at")

        if not spreadsheet_id:
            return

        # Check the spreadsheet's last modified time
        current_modified = await sheets_service.get_spreadsheet_modified_time(spreadsheet_id)

        if not current_modified:
            logger.warning(f"Could not get modified time for {band_id}")
            return

        # If the sheet hasn't changed since last sync, skip
        if last_sheet_modified and current_modified == last_sheet_modified:
            return

        logger.info(f"Sheet changed for {band_id}, syncing students...")

        # Sync students
        result = await self._sync_students(band_id, spreadsheet_id, active_list)

        # Update the school's last sync time and sheet modified time
        now = datetime.utcnow().isoformat()
        await update_school(
            band_id,
            last_synced_at=now,
            sheet_modified_at=current_modified,
        )

        logger.info(
            f"Synced {band_id}: {result['created']} created, "
            f"{result['updated']} updated, {result['deleted']} deleted"
        )

    async def _sync_students(
        self,
        band_id: str,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> dict:
        """
        Sync students from Google Sheets to the API database.

        Returns dict with created, updated, deleted counts.
        """
        # Get students from sheet
        sheet_students = await sheets_service.get_all_students_from_sheet(
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
        )

        # Get current students from API
        api_students = await get_all_students(band_id)
        api_students_by_name = {s["name"]: s for s in api_students}

        created = 0
        updated = 0

        # Track valid names for orphan deletion
        valid_names = []

        for student in sheet_students:
            name = student.get("name")
            if not name:
                continue

            valid_names.append(name)
            existing = api_students_by_name.get(name)

            if existing:
                # Check if instrument changed (we don't overwrite UID/code from sheet)
                needs_update = False
                if student.get("instrument") and student["instrument"] != existing.get("instrument"):
                    needs_update = True

                if needs_update:
                    await upsert_student(
                        band_id=band_id,
                        name=name,
                        instrument=student.get("instrument"),
                        # Don't pass uid/student_code - preserve existing values
                    )
                    updated += 1
            else:
                # New student - create with instrument, no UID/code yet
                await upsert_student(
                    band_id=band_id,
                    name=name,
                    instrument=student.get("instrument"),
                    uid=student.get("uid"),  # May be present in old sheets
                )
                created += 1

        # Delete students no longer in sheet
        deleted = await delete_students_not_in_list(band_id, valid_names)

        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "total_in_sheet": len(sheet_students),
        }


# Global worker instance
student_sync_worker = StudentSyncWorker()
