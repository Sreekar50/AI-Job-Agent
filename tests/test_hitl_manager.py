"""Tests for HITL manager."""
import asyncio
import pytest
from unittest.mock import AsyncMock
from backend.utils.hitl_manager import HITLManager


@pytest.fixture
def hitl():
    mgr = HITLManager()
    mgr.set_broadcaster(AsyncMock())
    return mgr


@pytest.mark.asyncio
async def test_hitl_answer_in_time(hitl):
    """User submits answer within timeout."""
    async def submit_later():
        await asyncio.sleep(0.1)
        hitl.submit_answer("job-1", "My answer")

    task = asyncio.create_task(submit_later())
    answer = await hitl.request_answer(
        job_id="job-1",
        field_label="Notice Period",
        timeout_override=5,  # 5s for test
    )
    await task
    assert answer == "My answer"


@pytest.mark.asyncio
async def test_hitl_timeout(hitl):
    """Returns None when timeout expires."""
    # Patch timeout to 0.1s
    import backend.utils.hitl_manager as hm
    original = hm.settings.HITL_TIMEOUT_SECONDS
    hm.settings.HITL_TIMEOUT_SECONDS = 0.1

    answer = await hitl.request_answer(
        job_id="job-2",
        field_label="Some sensitive field",
    )
    hm.settings.HITL_TIMEOUT_SECONDS = original
    assert answer is None


def test_get_pending_none(hitl):
    assert hitl.get_pending("nonexistent") is None


def test_submit_answer_no_pending(hitl):
    result = hitl.submit_answer("nonexistent", "answer")
    assert result is False
