"""
FastAPI application factory with lifespan management.
Connects to local PostgreSQL (no Docker needed).
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import get_settings
from app.database import init_db
from app.services.vector_store import get_vector_store

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting Codeforces RAG Assistant...")

    # Create data directory (needed for FAISS index)
    os.makedirs("./data", exist_ok=True)

    try:
        await init_db()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Make sure PostgreSQL is running and the database 'codeforces_rag' exists.")
        logger.error("To create it: psql -U postgres -c 'CREATE DATABASE codeforces_rag;'")
        raise

    # Initialize FAISS
    vs = get_vector_store()
    logger.info(f"FAISS index loaded ({vs.total_vectors} vectors)")

    yield

    # Shutdown
    vs = get_vector_store()
    vs.save()
    logger.info("FAISS index saved. Goodbye!")


app = FastAPI(
    title="Codeforces RAG Assistant",
    description="RAG-powered assistant for exploring and understanding Codeforces problems",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
from app.routers import chat, problems, ingest

app.include_router(chat.router)
app.include_router(problems.router)
app.include_router(ingest.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "codeforces-rag-assistant"}


# Mount frontend static files LAST (catch-all for SPA routing)
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
