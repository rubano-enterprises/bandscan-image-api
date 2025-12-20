"""Student request management endpoints."""

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from ..auth import verify_token
from ..database import (
    get_school,
    get_student_by_name,
    create_student_request,
    get_student_request,
    get_student_requests,
    resolve_student_request,
    delete_student_request,
    update_student,
)
from ..services import sheets_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schools/{band_id}/requests", tags=["Student Requests"])


# ============================================================================
# Request/Response Models
# ============================================================================

class RequestCreate(BaseModel):
    """Request model for creating a student request."""
    student_name: str
    request_type: str  # nameChange, instrumentChange, loanerRequest, lostTag
    new_value: str


class RequestResolve(BaseModel):
    """Request model for resolving a student request."""
    action: str  # approve, deny
    admin_response: Optional[str] = None


class RequestResponse(BaseModel):
    """Response model for a student request."""
    id: str
    band_id: str
    student_name: str
    request_type: str
    new_value: str
    status: str
    admin_response: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.get("")
async def list_requests(
    band_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    request_type: Optional[str] = Query(None),
    student_name: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    _token: str = Depends(verify_token),
):
    """
    List student requests for a school.

    Filters:
    - status: pending, approved, denied
    - request_type: nameChange, instrumentChange, loanerRequest, lostTag
    - student_name: filter by student
    """
    # Verify school exists
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )

    requests = await get_student_requests(
        band_id=band_id,
        status=status_filter,
        request_type=request_type,
        student_name=student_name,
        limit=limit,
        offset=offset,
    )

    return {
        "requests": requests,
        "count": len(requests),
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_request(
    band_id: str,
    request: RequestCreate,
    _token: str = Depends(verify_token),
):
    """
    Create a new student request.

    Request types:
    - nameChange: Student requests a name correction
    - instrumentChange: Student requests to change their instrument
    - loanerRequest: Student requests a loaner instrument
    - lostTag: Student reports a lost NFC tag
    """
    # Verify school exists
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )

    # Validate request type
    valid_types = ["nameChange", "instrumentChange", "loanerRequest", "lostTag"]
    if request.request_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request_type. Must be one of: {', '.join(valid_types)}"
        )

    # Verify student exists in API database
    student = await get_student_by_name(band_id, request.student_name)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{request.student_name}' not found"
        )

    # Check for existing pending request of same type
    existing = await get_student_requests(
        band_id=band_id,
        status="pending",
        request_type=request.request_type,
        student_name=request.student_name,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student already has a pending {request.request_type} request"
        )

    try:
        request_id = str(uuid4())
        created = await create_student_request(
            request_id=request_id,
            band_id=band_id,
            student_name=request.student_name,
            request_type=request.request_type,
            new_value=request.new_value,
        )
        logger.info(f"Created request {request_id} for {request.student_name} in {band_id}")
        return created
    except Exception as e:
        logger.error(f"Error creating request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{request_id}")
async def get_request(
    band_id: str,
    request_id: str,
    _token: str = Depends(verify_token),
):
    """Get a specific student request."""
    request = await get_student_request(request_id)
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # Verify request belongs to this school
    if request.get("band_id") != band_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    return request


@router.put("/{request_id}/resolve")
async def resolve_request(
    band_id: str,
    request_id: str,
    resolution: RequestResolve,
    _token: str = Depends(verify_token),
):
    """
    Resolve a student request (approve or deny).

    When approved:
    - nameChange: Updates student name in Google Sheets (Column A)
    - instrumentChange: Updates instrument in Google Sheets (Column B)
    - loanerRequest: No sheet update, just marks as approved
    - lostTag: Clears the student's UID in the API database
    """
    # Validate action
    if resolution.action not in ("approve", "deny"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be 'approve' or 'deny'"
        )

    # Get the request
    request = await get_student_request(request_id)
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # Verify request belongs to this school
    if request.get("band_id") != band_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # Check if already resolved
    if request.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request already {request.get('status')}"
        )

    # Get school for spreadsheet info
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )

    request_type = request.get("request_type")
    new_value = request.get("new_value")
    student_name = request.get("student_name")
    new_status = "approved" if resolution.action == "approve" else "denied"

    try:
        # If approving, apply the change
        if resolution.action == "approve":
            if request_type == "nameChange":
                # Update name in Google Sheets
                await sheets_service.update_student_name(
                    spreadsheet_id=school.get("student_list_spreadsheet_id"),
                    sheet_name=school.get("active_student_list", "FullBand"),
                    old_name=student_name,
                    new_name=new_value,
                )
                logger.info(f"Updated name in Sheets: {student_name} -> {new_value}")

            elif request_type == "instrumentChange":
                # Update instrument in Google Sheets
                await sheets_service.update_student_instrument(
                    spreadsheet_id=school.get("student_list_spreadsheet_id"),
                    sheet_name=school.get("active_student_list", "FullBand"),
                    student_name=student_name,
                    new_instrument=new_value,
                )
                logger.info(f"Updated instrument in Sheets for {student_name}: {new_value}")

            elif request_type == "lostTag":
                # Clear the student's UID in API database
                await update_student(band_id, student_name, uid=None)
                logger.info(f"Cleared UID for {student_name} due to lost tag")

            # loanerRequest doesn't need any automated action

        # Update request status in database
        resolved = await resolve_student_request(
            request_id=request_id,
            status=new_status,
            admin_response=resolution.admin_response,
        )

        logger.info(f"Resolved request {request_id} as {new_status}")
        return resolved

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error resolving request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve request: {e}"
        )


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(
    band_id: str,
    request_id: str,
    _token: str = Depends(verify_token),
):
    """
    Cancel (delete) a student request.

    Only pending requests can be cancelled.
    """
    # Get the request
    request = await get_student_request(request_id)
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # Verify request belongs to this school
    if request.get("band_id") != band_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # Only allow cancelling pending requests
    if request.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a request that is already {request.get('status')}"
        )

    deleted = await delete_student_request(request_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    logger.info(f"Cancelled request {request_id}")
