"""Student request endpoints."""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import verify_token
from ..database import queue_student_request
from ..services import sheets_service

router = APIRouter(prefix="/students", tags=["students"])


class StudentRequestCreate(BaseModel):
    """Request to create a student request."""
    spreadsheet_id: str
    sheet_name: str
    student_code: Optional[str] = None
    student_uid: Optional[str] = None
    request_type: str  # "nameChange", "instrumentChange", "loanerRequest"
    new_value: str


class StudentRequestResponse(BaseModel):
    """Response for a created student request."""
    id: str
    type: str
    new_value: str
    timestamp: str
    status: str


class ClaimTagRequest(BaseModel):
    """Request to claim an NFC tag."""
    spreadsheet_id: str
    sheet_name: str
    student_code: str
    new_uid: str


class ClaimTagResponse(BaseModel):
    """Response for claiming a tag."""
    success: bool
    message: str


class UidAvailabilityRequest(BaseModel):
    """Request to check UID availability."""
    spreadsheet_id: str
    sheet_name: str
    uid: str


class UidAvailabilityResponse(BaseModel):
    """Response for UID availability check."""
    available: bool


@router.post(
    "/requests",
    response_model=StudentRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_student_request(
    request: StudentRequestCreate,
    _: str = Depends(verify_token),
):
    """
    Create a new student request.

    Students can request name changes, instrument changes, or loaner instruments.
    The request is queued for async processing and returns immediately.
    """
    if not request.student_code and not request.student_uid:
        raise HTTPException(
            status_code=400,
            detail="Either student_code or student_uid is required",
        )

    valid_types = ["nameChange", "instrumentChange", "loanerRequest", "lostTag"]
    if request.request_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request_type. Must be one of: {', '.join(valid_types)}",
        )

    try:
        # Generate request ID and timestamp now for immediate response
        request_id = str(uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Queue the request for async processing
        # The original timestamp is preserved and will be written to Sheets
        await queue_student_request(
            request_id=request_id,
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            request_type=request.request_type,
            new_value=request.new_value,
            request_timestamp=timestamp,
            student_code=request.student_code,
            student_uid=request.student_uid,
        )

        # Return immediately - worker will process asynchronously
        return StudentRequestResponse(
            id=request_id,
            type=request.request_type,
            new_value=request.new_value,
            timestamp=timestamp,
            status="pending",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue request: {e}")


@router.post(
    "/claim-tag",
    response_model=ClaimTagResponse,
)
async def claim_tag(
    request: ClaimTagRequest,
    _: str = Depends(verify_token),
):
    """
    Claim an NFC tag for a student.

    The student must not already have a tag, and the tag must not already be assigned.
    """
    try:
        # Check if UID is available
        is_available = await sheets_service.verify_uid_available(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            uid=request.new_uid,
        )

        if not is_available:
            raise HTTPException(
                status_code=409,
                detail="This tag is already assigned to another student",
            )

        # Assign the UID
        success = await sheets_service.update_student_uid(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            student_code=request.student_code,
            new_uid=request.new_uid,
        )

        return ClaimTagResponse(
            success=success,
            message="Tag claimed successfully" if success else "Failed to claim tag",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to claim tag: {e}")


@router.post(
    "/check-uid-available",
    response_model=UidAvailabilityResponse,
)
async def check_uid_available(
    request: UidAvailabilityRequest,
    _: str = Depends(verify_token),
):
    """
    Check if an NFC tag UID is available for claiming.
    """
    try:
        is_available = await sheets_service.verify_uid_available(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            uid=request.uid,
        )

        return UidAvailabilityResponse(available=is_available)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check UID: {e}")
