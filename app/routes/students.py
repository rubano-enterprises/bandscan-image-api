"""Student management and request endpoints."""

from datetime import datetime, timezone
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from ..auth import verify_token
from ..database import (
    queue_student_request,
    get_student_by_name,
    get_student_by_uid,
    get_student_by_code,
    get_all_students as db_get_all_students,
    upsert_student,
    update_student,
    delete_student,
    check_student_code_exists,
)
from ..services import sheets_service

router = APIRouter(prefix="/students", tags=["Students"])


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


# New models for student management (API database)
class StudentCreate(BaseModel):
    """Request to create a student in API database."""
    name: str
    uid: Optional[str] = None
    student_code: Optional[str] = None


class StudentUpdate(BaseModel):
    """Request to update a student in API database."""
    uid: Optional[str] = None
    student_code: Optional[str] = None


class StudentResponse(BaseModel):
    """Response model for a student."""
    id: int
    band_id: str
    name: str
    uid: Optional[str] = None
    student_code: Optional[str] = None
    created_at: str
    updated_at: str


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


# ============================================================================
# Student Management Endpoints (API Database)
# These store UID and auth codes linked to student names
# ============================================================================

@router.get("/{band_id}/all")
async def get_all_students(
    band_id: str,
    _: str = Depends(verify_token),
):
    """Get all students for a school from API database."""
    students = await db_get_all_students(band_id)
    return {"students": students, "count": len(students)}


@router.get("/{band_id}/by-name/{name}")
async def get_student_by_name_endpoint(
    band_id: str,
    name: str,
    _: str = Depends(verify_token),
):
    """Get a student by name from API database."""
    student = await get_student_by_name(band_id, name)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{name}' not found"
        )
    return student


@router.get("/{band_id}/by-uid/{uid}")
async def get_student_by_uid_endpoint(
    band_id: str,
    uid: str,
    _: str = Depends(verify_token),
):
    """
    Get a student by NFC UID from API database.

    Used for NFC tag login - looks up student name by their tag UID.
    """
    student = await get_student_by_uid(band_id, uid)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student with this UID not found"
        )
    return student


@router.get("/{band_id}/by-code/{code}")
async def get_student_by_code_endpoint(
    band_id: str,
    code: str,
    _: str = Depends(verify_token),
):
    """
    Get a student by auth code from API database.

    Used for QR code login - looks up student name by their 6-char code.
    """
    student = await get_student_by_code(band_id, code)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student with this code not found"
        )
    return student


@router.post("/{band_id}", status_code=status.HTTP_201_CREATED)
async def create_student(
    band_id: str,
    request: StudentCreate,
    _: str = Depends(verify_token),
):
    """
    Create a new student in API database.

    Student name must be unique within the school.
    """
    # Check if name already exists
    existing = await get_student_by_name(band_id, request.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student '{request.name}' already exists"
        )

    # Check if code is unique if provided
    if request.student_code:
        code_exists = await check_student_code_exists(request.student_code)
        if code_exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This student code is already in use"
            )

    student = await upsert_student(
        band_id=band_id,
        name=request.name,
        uid=request.uid,
        student_code=request.student_code,
    )
    return student


@router.put("/{band_id}/{name}")
async def update_student_endpoint(
    band_id: str,
    name: str,
    request: StudentUpdate,
    _: str = Depends(verify_token),
):
    """Update a student's UID or auth code in API database."""
    existing = await get_student_by_name(band_id, name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{name}' not found"
        )

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return existing

    # Check if new code is unique if provided
    if request.student_code and request.student_code != existing.get("student_code"):
        code_exists = await check_student_code_exists(request.student_code)
        if code_exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This student code is already in use"
            )

    updated = await update_student(band_id, name, **updates)
    return updated


@router.delete("/{band_id}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_endpoint(
    band_id: str,
    name: str,
    _: str = Depends(verify_token),
):
    """Delete a student from API database."""
    deleted = await delete_student(band_id, name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{name}' not found"
        )


@router.get("/code-exists/{code}")
async def check_code_exists(
    code: str,
    _: str = Depends(verify_token),
):
    """Check if a student code exists (globally unique)."""
    exists = await check_student_code_exists(code)
    return {"code": code, "exists": exists}
