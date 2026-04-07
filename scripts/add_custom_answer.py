"""
CLI to add a custom answer to a candidate's profile.
New answers are automatically picked up on the next agent run.

Usage:
    python scripts/add_custom_answer.py --key notice_period --value "30 days"
    python scripts/add_custom_answer.py --key salary_expectation --value "150000" --candidate <id>
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from loguru import logger
from sqlalchemy import select

from backend.db.database import AsyncSessionLocal
from backend.db.models import Candidate, CustomAnswer


async def add_answer(candidate_id: str, key: str, value: str, description: str = ""):
    async with AsyncSessionLocal() as db:
        # Verify candidate
        result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Upsert
        result = await db.execute(
            select(CustomAnswer).where(
                CustomAnswer.candidate_id == candidate_id,
                CustomAnswer.question_key == key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            old = existing.answer
            existing.answer = value
            existing.description = description or existing.description
            logger.info(f"Updated '{key}': '{old}' → '{value}'")
        else:
            db.add(CustomAnswer(
                candidate_id=candidate_id,
                question_key=key,
                answer=value,
                description=description,
            ))
            logger.info(f"Added '{key}' = '{value}'")
        await db.commit()


async def get_first_candidate_id() -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Candidate).limit(1))
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("No candidates in DB")
        return candidate.id


async def main():
    parser = argparse.ArgumentParser(description="Add custom answer to candidate profile")
    parser.add_argument("--key", required=True, help="Question key (e.g. notice_period)")
    parser.add_argument("--value", required=True, help="Answer value")
    parser.add_argument("--candidate", help="Candidate ID (defaults to first)")
    parser.add_argument("--description", default="", help="Optional description")
    args = parser.parse_args()

    candidate_id = args.candidate or await get_first_candidate_id()
    await add_answer(candidate_id, args.key, args.value, args.description)
    logger.info("Done. This answer will be used on the next agent run.")


if __name__ == "__main__":
    asyncio.run(main())
