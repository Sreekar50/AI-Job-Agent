"""
CLI runner — processes the full job queue for a candidate.

Usage:
    python scripts/run_agent.py                    # uses first candidate in DB
    python scripts/run_agent.py <candidate_id>     # specific candidate
    python scripts/run_agent.py --job <job_id>     # single job
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from loguru import logger
from sqlalchemy import select

from backend.db.database import AsyncSessionLocal
from backend.db.models import Candidate, Job, JobStatus
from backend.api.candidates import candidate_to_profile_dict
from backend.agents.job_agent import run_queue, run_job_agent
from sqlalchemy.orm import selectinload


async def get_profile(candidate_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Candidate)
            .where(Candidate.id == candidate_id)
            .options(
                selectinload(Candidate.work_experiences),
                selectinload(Candidate.educations),
                selectinload(Candidate.skills),
                selectinload(Candidate.custom_answers),
            )
        )
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate_to_profile_dict(candidate)


async def get_first_candidate_id() -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Candidate).limit(1))
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("No candidates in database. Run: python scripts/seed_demo.py")
        return candidate.id


async def main():
    parser = argparse.ArgumentParser(description="AI Job Application Agent Runner")
    parser.add_argument("candidate_id", nargs="?", help="Candidate ID (optional, defaults to first candidate)")
    parser.add_argument("--job", help="Single job ID to process")
    parser.add_argument("--list", action="store_true", help="List all queued jobs")
    args = parser.parse_args()

    if args.candidate_id:
        candidate_id = args.candidate_id
    else:
        candidate_id = await get_first_candidate_id()
        logger.info(f"Using candidate: {candidate_id}")

    if args.list:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Job).where(Job.candidate_id == candidate_id).order_by(Job.created_at)
            )
            jobs = result.scalars().all()
        print(f"\nJobs for candidate {candidate_id}:")
        print(f"{'ID':<38} {'Status':<12} {'URL'}")
        print("-" * 100)
        for j in jobs:
            print(f"{j.id:<38} {j.status:<12} {j.url[:60]}")
        return

    profile = await get_profile(candidate_id)
    logger.info(f"Loaded profile for: {profile['full_name']}")

    if args.job:
        logger.info(f"Running single job: {args.job}")
        await run_job_agent(args.job, profile)
    else:
        logger.info(f"Running full queue for candidate {candidate_id}")
        await run_queue(candidate_id, profile)


if __name__ == "__main__":
    asyncio.run(main())
