"""
HITL Demo Script

Simulates a HITL event for demo/screen recording purposes.
Shows both paths:
  1. User responds in time → answer saved to custom_answers, agent continues
  2. No response → job moves to backlog

Run: python scripts/demo_hitl.py          # Path 1: responds in time
Run: python scripts/demo_hitl.py timeout  # Path 2: timeout / backlog
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from backend.utils.hitl_manager import hitl_manager
from backend.utils.config import settings


async def _auto_submit(job_id: str, answer: str, delay: float = 5.0):
    """
    Simulates the user submitting an answer after `delay` seconds.
    Runs concurrently alongside request_answer() so it resolves the Future
    before the 30s timeout fires.
    """
    await asyncio.sleep(delay)
    success = hitl_manager.submit_answer(job_id, answer)
    if success:
        logger.info(f"[AUTO-SUBMIT] Submitted answer for job '{job_id}': '{answer}'")
    else:
        logger.warning(f"[AUTO-SUBMIT] Could not submit — no pending request for '{job_id}'")


async def simulate_hitl_respond():
    """Path 1: HITL fires, user answers in time → saved to DB."""
    logger.info("=" * 55)
    logger.info("DEMO: Simulating HITL — user responds in time")
    logger.info("=" * 55)

    job_id = "demo-job-001"

    # KEY FIX: schedule the simulated user response BEFORE awaiting request_answer.
    # This runs concurrently — submit fires after 5s, well within the 30s window.
    asyncio.ensure_future(_auto_submit(job_id, answer="$120,000", delay=5.0))

    answer = await hitl_manager.request_answer(
        job_id=job_id,
        field_label="Expected Salary (USD)",
        field_type="text",
        field_options=None,
        context=(
            "Field: Expected Salary (USD)\n"
            "Type: text\n"
            "LLM suggestion: N/A (sensitive — escalated)\n"
            "Options: Free text"
        ),
    )

    if answer:
        logger.success(f"HITL resolved: 'Expected Salary' = '{answer}'")
        logger.info("Answer will be saved to custom_answers for future runs.")
    else:
        logger.warning("HITL timeout — job moved to backlog.")


async def simulate_hitl_timeout():
    """Path 2: HITL fires, user doesn't respond → backlog."""
    logger.info("=" * 55)
    logger.info("DEMO: Simulating HITL timeout (no response)")
    logger.info(f"Waiting {settings.HITL_TIMEOUT_SECONDS}s...")
    logger.info("=" * 55)

    # No _auto_submit scheduled — intentionally let it time out.
    answer = await hitl_manager.request_answer(
        job_id="demo-job-002",
        field_label="Willing to relocate to Austin, TX?",
        field_type="select",
        field_options=["Yes", "No", "Open to discussion"],
        context=(
            "Field: Willing to relocate to Austin, TX?\n"
            "Type: select\n"
            "LLM suggestion: N/A (sensitive — escalated)\n"
            "Options: Yes, No, Open to discussion"
        ),
    )

    if answer is None:
        logger.warning("HITL timeout — job 'demo-job-002' → BACKLOG")
        logger.info("Agent will continue to next job in queue immediately.")
    else:
        logger.success(f"Got answer: '{answer}'")


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "respond"

    if mode == "timeout":
        await simulate_hitl_timeout()
    else:
        await simulate_hitl_respond()


if __name__ == "__main__":
    asyncio.run(main())