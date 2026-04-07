"""
Celery Worker

Enables concurrent job processing with isolated workers.
Each worker picks up one job at a time from the Redis queue.
"""
import asyncio
from celery import Celery
from loguru import logger

from backend.utils.config import settings

celery_app = Celery(
    "job_agent",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # one job at a time per worker
)


@celery_app.task(name="process_job", bind=True, max_retries=2)
def process_job_task(self, job_id: str, candidate_profile: dict):
    """Celery task: run the full agent pipeline for one job."""
    from backend.agents.job_agent import run_job_agent

    logger.info(f"[Celery] Starting job {job_id}")
    try:
        asyncio.run(run_job_agent(job_id, candidate_profile))
        logger.info(f"[Celery] Completed job {job_id}")
    except Exception as e:
        logger.error(f"[Celery] Job {job_id} failed: {e}")
        raise self.retry(exc=e, countdown=30)


@celery_app.task(name="process_queue")
def process_queue_task(candidate_id: str, candidate_profile: dict):
    """Celery task: process all queued jobs for a candidate."""
    from backend.agents.job_agent import run_queue

    logger.info(f"[Celery] Starting queue for candidate {candidate_id}")
    asyncio.run(run_queue(candidate_id, candidate_profile))
