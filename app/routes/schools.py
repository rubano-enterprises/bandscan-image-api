"""School configuration and sheet mapping endpoints."""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from ..auth import verify_token
from ..database import (
    get_school,
    get_all_schools,
    upsert_school,
    update_school,
    delete_school,
    get_school_sheets,
    get_active_bus_sheets,
    add_school_sheet,
    remove_school_sheet,
    set_bus_sheet_active,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schools", tags=["Schools"])


# ============================================================================
# Request/Response Models
# ============================================================================

class SchoolCreate(BaseModel):
    """Request model for creating a school."""
    band_id: str
    student_list_spreadsheet_id: str
    short_name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    full_name: Optional[str] = None
    admin_emails: Optional[str] = None
    attendance_template_id: Optional[str] = None
    inventory_sheet_id: Optional[str] = None
    active_student_list: str = "FullBand"


class SchoolUpdate(BaseModel):
    """Request model for updating a school."""
    student_list_spreadsheet_id: Optional[str] = None
    short_name: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    full_name: Optional[str] = None
    admin_emails: Optional[str] = None
    attendance_template_id: Optional[str] = None
    inventory_sheet_id: Optional[str] = None
    active_student_list: Optional[str] = None


class ActiveListUpdate(BaseModel):
    """Request model for updating active student list."""
    active_student_list: str


class SheetAdd(BaseModel):
    """Request model for adding a sheet."""
    sheet_id: str
    is_active: bool = False
    display_order: int = 0


class BusSheetActiveUpdate(BaseModel):
    """Request model for setting bus sheet active status."""
    is_active: bool


# ============================================================================
# School Endpoints
# ============================================================================

@router.get("")
async def list_schools(_token: str = Depends(verify_token)):
    """List all schools."""
    schools = await get_all_schools()
    return {"schools": schools, "count": len(schools)}


@router.get("/{band_id}")
async def get_school_config(
    band_id: str,
    _token: str = Depends(verify_token),
):
    """Get a school's configuration."""
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )
    return school


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_school(
    request: SchoolCreate,
    _token: str = Depends(verify_token),
):
    """Create a new school."""
    try:
        school = await upsert_school(
            band_id=request.band_id,
            student_list_spreadsheet_id=request.student_list_spreadsheet_id,
            short_name=request.short_name,
            logo_url=request.logo_url,
            primary_color=request.primary_color,
            full_name=request.full_name,
            admin_emails=request.admin_emails,
            attendance_template_id=request.attendance_template_id,
            inventory_sheet_id=request.inventory_sheet_id,
            active_student_list=request.active_student_list,
        )
        logger.info(f"Created/updated school: {request.band_id}")
        return school
    except Exception as e:
        logger.error(f"Error creating school: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/{band_id}")
async def update_school_config(
    band_id: str,
    request: SchoolUpdate,
    _token: str = Depends(verify_token),
):
    """Update a school's configuration."""
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return school

    try:
        updated = await update_school(band_id, **updates)
        logger.info(f"Updated school {band_id}: {list(updates.keys())}")
        return updated
    except Exception as e:
        logger.error(f"Error updating school: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{band_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_school_endpoint(
    band_id: str,
    _token: str = Depends(verify_token),
):
    """Delete a school and all related data."""
    deleted = await delete_school(band_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )
    logger.info(f"Deleted school: {band_id}")


# ============================================================================
# Active Student List Endpoints
# ============================================================================

@router.get("/{band_id}/active-list")
async def get_active_student_list(
    band_id: str,
    _token: str = Depends(verify_token),
):
    """Get the active student list name for a school."""
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )
    return {"active_student_list": school.get("active_student_list", "FullBand")}


@router.put("/{band_id}/active-list")
async def set_active_student_list(
    band_id: str,
    request: ActiveListUpdate,
    _token: str = Depends(verify_token),
):
    """Set the active student list name for a school."""
    school = await get_school(band_id)
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{band_id}' not found"
        )

    updated = await update_school(band_id, active_student_list=request.active_student_list)
    logger.info(f"Set active student list for {band_id}: {request.active_student_list}")
    return {"active_student_list": updated.get("active_student_list")}


# ============================================================================
# Sheet Mapping Endpoints
# ============================================================================

@router.get("/{band_id}/sheets/{sheet_type}")
async def list_sheets(
    band_id: str,
    sheet_type: str,
    _token: str = Depends(verify_token),
):
    """List all sheets of a specific type for a school.

    sheet_type can be: attendance, checkin, bus
    """
    if sheet_type not in ("attendance", "checkin", "bus"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_type must be 'attendance', 'checkin', or 'bus'"
        )

    sheets = await get_school_sheets(band_id, sheet_type)

    # For bus sheets, also indicate which are active
    if sheet_type == "bus":
        active_ids = await get_active_bus_sheets(band_id)
        for sheet in sheets:
            sheet["is_active"] = sheet["sheet_id"] in active_ids

    return {
        "band_id": band_id,
        "sheet_type": sheet_type,
        "sheets": sheets,
        "count": len(sheets)
    }


@router.post("/{band_id}/sheets/{sheet_type}", status_code=status.HTTP_201_CREATED)
async def add_sheet(
    band_id: str,
    sheet_type: str,
    request: SheetAdd,
    _token: str = Depends(verify_token),
):
    """Add a sheet to a school."""
    if sheet_type not in ("attendance", "checkin", "bus"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_type must be 'attendance', 'checkin', or 'bus'"
        )

    try:
        sheet = await add_school_sheet(
            band_id=band_id,
            sheet_type=sheet_type,
            sheet_id=request.sheet_id,
            is_active=request.is_active if sheet_type == "bus" else False,
            display_order=request.display_order,
        )
        logger.info(f"Added {sheet_type} sheet {request.sheet_id} to {band_id}")
        return sheet
    except Exception as e:
        logger.error(f"Error adding sheet: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{band_id}/sheets/{sheet_type}/{sheet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_sheet(
    band_id: str,
    sheet_type: str,
    sheet_id: str,
    _token: str = Depends(verify_token),
):
    """Remove a sheet from a school."""
    if sheet_type not in ("attendance", "checkin", "bus"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_type must be 'attendance', 'checkin', or 'bus'"
        )

    removed = await remove_school_sheet(band_id, sheet_type, sheet_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sheet not found"
        )
    logger.info(f"Removed {sheet_type} sheet {sheet_id} from {band_id}")


@router.put("/{band_id}/sheets/bus/{sheet_id}/active")
async def set_bus_active(
    band_id: str,
    sheet_id: str,
    request: BusSheetActiveUpdate,
    _token: str = Depends(verify_token),
):
    """Set the active status of a bus sheet."""
    success = await set_bus_sheet_active(band_id, sheet_id, request.is_active)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bus sheet not found"
        )

    logger.info(f"Set bus sheet {sheet_id} active={request.is_active} for {band_id}")
    return {"sheet_id": sheet_id, "is_active": request.is_active}


@router.get("/{band_id}/sheets/bus/active")
async def list_active_bus_sheets(
    band_id: str,
    _token: str = Depends(verify_token),
):
    """Get all active bus sheet IDs for a school."""
    active_ids = await get_active_bus_sheets(band_id)
    return {
        "band_id": band_id,
        "active_sheet_ids": active_ids,
        "count": len(active_ids)
    }
