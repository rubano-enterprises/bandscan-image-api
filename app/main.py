"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_database
from .routes import health, images, items, students, tokens, notifications, schools, requests
from .services.queue_worker import queue_worker

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Initializing database...")
    await init_database()
    logger.info("Database initialized")

    logger.info("Starting queue worker...")
    await queue_worker.start()
    logger.info("Queue worker started")

    logger.info(f"BandScan API starting on {settings.base_url}")

    yield

    # Shutdown
    logger.info("Stopping queue worker...")
    await queue_worker.stop()
    logger.info("BandScan API shutting down")


app = FastAPI(
    title="BandScan API",
    description="Unified API for BandScan app - handles images, notifications, device tokens, and operational data",
    version="2.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(images.router)
app.include_router(items.router)
app.include_router(students.router)
app.include_router(tokens.router)
app.include_router(notifications.router)
app.include_router(schools.router)
app.include_router(requests.router)


@app.get("/")
async def root():
    """Root endpoint redirect to docs."""
    return {"message": "BandScan API", "docs": "/docs"}
