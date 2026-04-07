"""
Jobs API

Handles:
- Adding jobs to the queue
- Triggering the agent pipeline
- Viewing job status and logs
- HITL answer submission
- Backlog management
"""
import asyncio
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Job, JobStatus, AgentLog, Candidate
from backend.api.candidates import get_candidate_or_404, candidate_to_profile_dict
from backend.utils.hitl_manager import hitl_manager

router = APIRouter()


# Schemas 

class JobCreate(BaseModel):
    candidate_id: str
    url: str
    company: Optional[str] = None
    title: Optional[str] = None

class HITLAnswerIn(BaseModel):
    answer: str

class BulkJobCreate(BaseModel):
    candidate_id: str
    urls: list[str]


# Routes

@router.post("", status_code=201)
async def add_job(data: JobCreate, db: AsyncSession = Depends(get_db)):
    """Add a single job to the queue."""
    job = Job(
        candidate_id=data.candidate_id,
        url=str(data.url),
        company=data.company,
        title=data.title,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    await db.commit()
    return {"id": job.id, "status": job.status, "message": "Job queued"}


@router.post("/bulk", status_code=201)
async def add_bulk_jobs(data: BulkJobCreate, db: AsyncSession = Depends(get_db)):
    """Add multiple jobs to the queue at once."""
    jobs = []
    for url in data.urls:
        job = Job(candidate_id=data.candidate_id, url=str(url), status=JobStatus.QUEUED)
        db.add(job)
        jobs.append(job)
    await db.commit()
    return {"count": len(jobs), "message": f"{len(jobs)} jobs queued"}


@router.get("")
async def list_jobs(
    candidate_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Job)
    if candidate_id:
        query = query.where(Job.candidate_id == candidate_id)
    if status:
        query = query.where(Job.status == status)
    query = query.order_by(Job.created_at.desc())
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [_job_to_dict(j) for j in jobs]


@router.get("/statuses")
async def get_statuses():
    return [s.value for s in JobStatus]


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(job_id, db)
    return _job_to_dict(job)


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentLog).where(AgentLog.job_id == job_id).order_by(AgentLog.created_at)
    )
    logs = result.scalars().all()
    return [{"step": l.step, "message": l.message, "data": l.data, "created_at": str(l.created_at)} for l in logs]


@router.post("/{job_id}/run")
async def run_job(job_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Trigger agent pipeline for a specific job."""
    job = await _get_job_or_404(job_id, db)

    if job.status not in [JobStatus.QUEUED, JobStatus.BACKLOG, JobStatus.FAILED]:
        raise HTTPException(400, f"Job is in status '{job.status}' — cannot run")

    candidate = await get_candidate_or_404(job.candidate_id, db)
    profile = candidate_to_profile_dict(candidate)

    background_tasks.add_task(_run_job_bg, job_id, profile)
    return {"message": f"Agent started for job {job_id}", "job_id": job_id}


@router.post("/run-queue/{candidate_id}")
async def run_queue(candidate_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Run the full job queue for a candidate (background)."""
    candidate = await get_candidate_or_404(candidate_id, db)
    profile = candidate_to_profile_dict(candidate)

    background_tasks.add_task(_run_queue_bg, candidate_id, profile)
    return {"message": f"Queue processing started for candidate {candidate_id}"}


@router.post("/{job_id}/hitl-answer")
async def submit_hitl_answer(job_id: str, data: HITLAnswerIn, db: AsyncSession = Depends(get_db)):
    """
    Submit a human answer for a pending HITL field.
    Called by the user within the 30-second window.
    """
    success = hitl_manager.submit_answer(job_id, data.answer)
    if not success:
        raise HTTPException(404, "No pending HITL request for this job (may have timed out)")
    return {"message": "Answer submitted", "answer": data.answer}


@router.get("/{job_id}/hitl-pending")
async def get_hitl_pending(job_id: str):
    """Get the currently pending HITL request for a job."""
    pending = hitl_manager.get_pending(job_id)
    if not pending:
        return {"pending": False}
    return {"pending": True, **pending}


@router.get("/hitl/all-pending")
async def get_all_hitl_pending():
    """Get all currently pending HITL requests."""
    return hitl_manager.get_all_pending()


@router.patch("/{job_id}/status")
async def update_job_status(job_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Manually update job status (e.g. requeue from backlog)."""
    job = await _get_job_or_404(job_id, db)
    new_status = data.get("status")
    if new_status not in [s.value for s in JobStatus]:
        raise HTTPException(400, f"Invalid status: {new_status}")
    job.status = new_status
    await db.commit()
    return {"message": f"Job status updated to {new_status}"}


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(job_id, db)
    await db.delete(job)
    await db.commit()
    return {"message": "Job deleted"}


# Helpers

async def _get_job_or_404(job_id: str, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _job_to_dict(j: Job) -> dict:
    return {
        "id": j.id,
        "candidate_id": j.candidate_id,
        "url": j.url,
        "company": j.company,
        "title": j.title,
        "ats_platform": j.ats_platform,
        "status": j.status,
        "failure_reason": j.failure_reason,
        "unanswered_fields": j.unanswered_fields,
        "tailored_resume_path": j.tailored_resume_path,
        "created_at": str(j.created_at),
        "started_at": str(j.started_at) if j.started_at else None,
        "applied_at": str(j.applied_at) if j.applied_at else None,
    }


async def _run_job_bg(job_id: str, profile: dict):
    from backend.agents.job_agent import run_job_agent
    await run_job_agent(job_id, profile)


async def _run_queue_bg(candidate_id: str, profile: dict):
    from backend.agents.job_agent import run_queue
    await run_queue(candidate_id, profile)
