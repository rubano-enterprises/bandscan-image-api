"""Health check endpoint."""

from fastapi import APIRouter

from ..database import get_queue_stats
from ..models import HealthResponse

router = APIRouter()

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint - no auth required."""
    return HealthResponse(status="healthy", version=VERSION)


@router.get("/health/queue")
async def queue_health():
    """Get queue stats for monitoring."""
    stats = await get_queue_stats()
    return {
        "status": "healthy",
        "queue": stats,
    }
