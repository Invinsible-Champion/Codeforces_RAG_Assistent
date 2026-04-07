"""
Ingestion API endpoints.
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session_factory
from app.schemas import IngestRequest, IngestStatusResponse
from app.services.ingestion import ingest_problems, get_ingestion_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["ingestion"])


async def _run_ingestion(tags, rating_min, rating_max, limit):
    """Run ingestion in the background with its own DB session."""
    async with async_session_factory() as db:
        try:
            await ingest_problems(
                db=db,
                tags=tags,
                rating_min=rating_min,
                rating_max=rating_max,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"Background ingestion error: {e}")


@router.post("/start")
async def start_ingestion(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
):
    """Start the ingestion pipeline (runs in background)."""
    status = get_ingestion_status()
    if status["running"]:
        return {"status": "already_running", "detail": status}

    background_tasks.add_task(
        _run_ingestion,
        tags=request.tags,
        rating_min=request.rating_min,
        rating_max=request.rating_max,
        limit=request.limit,
    )

    return {"status": "started", "detail": f"Ingesting up to {request.limit} problems"}


@router.get("/status")
async def ingestion_status():
    """Check ingestion pipeline status."""
    return IngestStatusResponse(**get_ingestion_status())
