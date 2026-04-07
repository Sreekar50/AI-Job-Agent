"""
AI Job Application Agent — FastAPI Entry Point
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.db.database import engine, Base
from backend.api import candidates, jobs, websocket_routes
from backend.utils.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Job Application Agent...")
    # Create tables on startup (use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready.")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="AI Job Application Agent",
    description="Autonomous end-to-end job application pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(candidates.router, prefix="/api/candidates", tags=["Candidates"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(websocket_routes.router, prefix="/ws", tags=["WebSocket"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-agent"}


@app.get("/")
async def root():
    return {
        "message": "AI Job Application Agent",
        "docs": "/docs",
        "health": "/health",
    }
