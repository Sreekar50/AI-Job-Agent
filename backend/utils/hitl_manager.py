"""
Human-in-the-Loop (HITL) Manager

Flow:
1. Agent hits an ambiguous field → calls request_answer()
2. Notification sent to all connected WebSocket clients
3. 30-second countdown begins
4. If user responds in time → answer saved, agent continues
5. If timeout → job moved to backlog, agent continues to next job

The 30s timeout, WebSocket broadcasting, and backlog logic are all here.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from loguru import logger

from backend.utils.config import settings


@dataclass
class HITLRequest:
    job_id: str
    field_label: str
    field_type: str
    field_options: Optional[list]
    context: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    future: Optional[asyncio.Future] = field(default=None, repr=False)


class HITLManager:
    """
    Manages human-in-the-loop escalation.
    Uses asyncio Futures + WebSocket broadcast for real-time HITL.
    """

    def __init__(self):
        self._pending: Dict[str, HITLRequest] = {}
        self._ws_broadcaster: Optional[Callable] = None  # injected by WebSocket handler

    def set_broadcaster(self, broadcaster: Callable):
        """Inject the WebSocket broadcast function."""
        self._ws_broadcaster = broadcaster

    async def request_answer(
        self,
        job_id: str,
        field_label: str,
        field_type: str = "text",
        field_options: Optional[list] = None,
        context: str = "",
    ) -> Optional[str]:
        """
        Request a human answer for a form field.
        Blocks for up to HITL_TIMEOUT_SECONDS seconds.
        Returns the answer string, or None on timeout.
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        request = HITLRequest(
            job_id=job_id,
            field_label=field_label,
            field_type=field_type,
            field_options=field_options,
            context=context,
            future=future,
        )
        self._pending[job_id] = request

        # Notify connected clients via WebSocket
        await self._broadcast_hitl_request(request)

        logger.info(
            f"HITL: Waiting {settings.HITL_TIMEOUT_SECONDS}s for answer to '{field_label}' (job={job_id})"
        )

        try:
            answer = await asyncio.wait_for(future, timeout=settings.HITL_TIMEOUT_SECONDS)
            logger.info(f"HITL: Got answer for '{field_label}': '{answer}'")
            return answer
        except asyncio.TimeoutError:
            logger.warning(
                f"HITL: Timeout on '{field_label}' for job {job_id} — moving to backlog"
            )
            return None
        finally:
            self._pending.pop(job_id, None)

    def submit_answer(self, job_id: str, answer: str) -> bool:
        """Called by the API when user submits an answer via WebSocket or REST."""
        request = self._pending.get(job_id)
        if not request or not request.future or request.future.done():
            logger.warning(f"HITL: No pending request for job {job_id}")
            return False

        request.future.set_result(answer)
        logger.info(f"HITL: Answer submitted for job {job_id}: '{answer}'")
        return True

    def get_pending(self, job_id: str) -> Optional[dict]:
        """Get pending HITL request info."""
        req = self._pending.get(job_id)
        if not req:
            return None
        elapsed = (datetime.utcnow() - req.created_at).total_seconds()
        remaining = max(0, settings.HITL_TIMEOUT_SECONDS - elapsed)
        return {
            "job_id": req.job_id,
            "field_label": req.field_label,
            "field_type": req.field_type,
            "field_options": req.field_options,
            "context": req.context,
            "timeout_seconds": settings.HITL_TIMEOUT_SECONDS,
            "seconds_remaining": round(remaining, 1),
        }

    def get_all_pending(self) -> list[dict]:
        return [self.get_pending(jid) for jid in list(self._pending.keys())]

    async def _broadcast_hitl_request(self, request: HITLRequest):
        """Broadcast HITL request to all connected WebSocket clients."""
        if self._ws_broadcaster:
            payload = {
                "type": "hitl_request",
                "job_id": request.job_id,
                "field_label": request.field_label,
                "field_type": request.field_type,
                "field_options": request.field_options,
                "context": request.context,
                "timeout_seconds": settings.HITL_TIMEOUT_SECONDS,
            }
            try:
                await self._ws_broadcaster(payload)
            except Exception as e:
                logger.error(f"HITL broadcast error: {e}")


# Singleton
hitl_manager = HITLManager()
