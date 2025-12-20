"""Background worker for processing queued student requests."""

import asyncio
import logging
from typing import Optional

from ..database import (
    get_pending_requests,
    mark_request_processed,
    mark_request_failed,
)
from . import sheets_service

logger = logging.getLogger(__name__)


class QueueWorker:
    """Background worker that processes pending student requests."""

    def __init__(self, poll_interval: float = 5.0):
        """
        Initialize the queue worker.

        Args:
            poll_interval: Seconds between queue checks
        """
        self._poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background worker."""
        if self._running:
            logger.warning("Queue worker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Queue worker started")

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
        logger.info("Queue worker stopped")

    async def _run(self):
        """Main worker loop."""
        while self._running:
            try:
                await self._process_queue()
            except Exception as e:
                logger.exception(f"Error in queue worker loop: {e}")

            # Wait before next poll
            await asyncio.sleep(self._poll_interval)

    async def _process_queue(self):
        """Process pending requests from the queue."""
        pending = await get_pending_requests(limit=10)

        if not pending:
            return

        logger.debug(f"Processing {len(pending)} pending requests")

        for request in pending:
            await self._process_request(request)

    async def _process_request(self, request: dict):
        """Process a single queued request."""
        request_id = request["id"]
        request_type = request["request_type"]

        try:
            logger.info(f"Processing request {request_id} ({request_type})")

            # Call the sheets service to write to Google Sheets
            # Pass the original timestamp so the student's request time is preserved
            await sheets_service.add_student_request(
                spreadsheet_id=request["spreadsheet_id"],
                sheet_name=request["sheet_name"],
                request_type=request_type,
                new_value=request["new_value"],
                student_code=request.get("student_code"),
                student_uid=request.get("student_uid"),
                request_id=request_id,
                request_timestamp=request.get("request_timestamp"),
            )

            # Mark as processed
            await mark_request_processed(request_id)
            logger.info(f"Request {request_id} processed successfully")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process request {request_id}: {error_msg}")
            # Move to end of queue so other items can process first
            await mark_request_failed(request_id, error=error_msg)


# Global worker instance
queue_worker = QueueWorker()
