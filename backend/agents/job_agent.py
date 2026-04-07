"""
LangGraph Agent Pipeline

The core agentic pipeline for processing one job application.

Graph nodes:
1. fetch_job_details    → load URL, extract job info, detect ATS
2. tailor_resume        → LLM tailors resume to JD
3. generate_cover_letter → LLM generates cover letter
4. fill_and_submit      → Browser fills + submits the application
5. log_result           → Update DB with outcome

Edges include conditional routing (HITL timeout → backlog, error → failed).
"""
import asyncio
import re
from datetime import datetime
from typing import TypedDict, Optional, Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from loguru import logger
from playwright.async_api import async_playwright

from backend.db.database import AsyncSessionLocal
from backend.db.models import Job, JobStatus, AgentLog, CustomAnswer, ATSPlatform
from backend.services.ats_detector import ats_detector
from backend.services.llm_service import llm_service
from backend.services.resume_service import resume_service
from backend.services.browser_service import BrowserService
from backend.services.field_resolver import HITLTimeoutError
from sqlalchemy import select


# Job Description Validation

# Patterns that indicate the fetched page is an error/404 page rather than a
# real job posting. Checked case-insensitively against the extracted text.
_ERROR_PAGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"page not found", re.I),
    re.compile(r"job (posting|listing).{0,30}(closed|removed|no longer|expired)", re.I),
    re.compile(r"no longer active", re.I),
    re.compile(r"sorry.{0,30}(find|available|exist)", re.I),
    re.compile(r"\b404\b", re.I),
    re.compile(r"this (job|position|role) (has been |is )(filled|closed|removed)", re.I),
    # HTTP error pages — catches "403 Forbidden", "Access Denied", etc.
    re.compile(r"^403\b", re.I),
    re.compile(r"\bforbidden\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
    # LLM admitting it found nothing (e.g. Workday SPA where body text is navigation only)
    re.compile(r"(description|text).{0,20}not provided", re.I),
    re.compile(r"not specified in the given", re.I),
    # LinkedIn-specific: language picker appears on 404 pages
    re.compile(r"bahasa indonesia.*bahasa malaysia.*dansk", re.I),
    # Amazon-specific error page text
    re.compile(r"the job you.{0,20}looking for isn.{0,5}t available", re.I),
]

# A real job description should have meaningful content length
_MIN_DESCRIPTION_LENGTH = 300


def _is_valid_job_description(text: str) -> bool:
    """
    Return True only if the text looks like a real job description.
    Rejects 404 pages, expired listings, and near-empty content.
    """
    if not text or len(text.strip()) < _MIN_DESCRIPTION_LENGTH:
        return False
    for pattern in _ERROR_PAGE_PATTERNS:
        if pattern.search(text):
            return False
    return True


# Agent State

class JobAgentState(TypedDict):
    job_id: str
    candidate_id: str
    candidate_profile: dict
    job_url: str
    job_description: str
    company: str
    title: str
    ats_platform: str
    tailored_resume_path: str
    cover_letter: str
    unanswered_fields: dict
    error: Optional[str]
    status: str          # maps to JobStatus
    hitl_new_answers: dict  # field_key → answer (to save to custom_answers)


# Agent Nodes

async def fetch_job_details(state: JobAgentState) -> JobAgentState:
    """
    Node 1: Load job URL, extract structured details, validate description.

    ── fix ──────────────────────────────────────────────────────────
    After fetching page text the agent now validates that it received a real
    job description and not a 404 / expired-listing error page.

    If the page text fails validation:
    • The job is marked FAILED immediately with a clear failure_reason.
    • Downstream nodes (tailor_resume, generate_cover_letter, fill_and_submit)
      are skipped via the should_continue_after_fetch routing function.
    • company and title are left as "Unknown" — no misleading data is stored.

    This also prevents the LLM from generating a cover letter for a job it
    knows nothing about (which was causing the generic-opener problem).
    ─────────────────────────────────────────────────────────────────────────
    """
    logger.info(f"[Agent] fetch_job_details for job {state['job_id']}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(state["job_url"], wait_until="domcontentloaded", timeout=60000)

            # ATS detection (URL-based, fast — no DOM needed yet)
            detection = await ats_detector.detect(state["job_url"], None)

            # ── SPA wait strategy ─────────────────────────────────────────
            # Workday, LinkedIn, and other JS-heavy SPAs render their content
            # asynchronously after domcontentloaded. Give them extra time to
            # settle before grabbing body text, otherwise we capture only the
            # navigation skeleton with no job description.
            _SPA_ATS = {ATSPlatform.WORKDAY, ATSPlatform.LINKEDIN}
            if detection.platform in _SPA_ATS:
                try:
                    # Wait up to 8s for any known content selector to appear
                    await page.wait_for_selector(
                        "[data-automation-id='jobPostingHeader'], "
                        ".jobs-details__main-content, "
                        ".job-description, "
                        "#job-description, "
                        "[class*='jobDescription']",
                        timeout=8000,
                    )
                except Exception:
                    # Selector not found — give the SPA a flat extra wait
                    await page.wait_for_timeout(5000)
            # ─────────────────────────────────────────────────────────────

            page_text = await page.inner_text("body")

            # Upgrade detection with DOM now that page has rendered
            if detection.platform == ATSPlatform.UNKNOWN:
                detection = await ats_detector.detect_from_dom(page, state["job_url"])

            await browser.close()

        # ── Validate page content before LLM extraction ───────────────────
        if not _is_valid_job_description(page_text):
            error_msg = (
                f"Job page does not contain a valid description "
                f"(length={len(page_text.strip())}, likely 404 or expired listing). "
                f"URL: {state['job_url']}"
            )
            logger.warning(f"[Agent] {error_msg}")
            await _log(
                state["job_id"],
                "fetch_job_details",
                "Job page invalid — skipping",
                {"url": state["job_url"], "page_length": len(page_text.strip())},
            )
            return {
                **state,
                "error": error_msg,
                "status": JobStatus.FAILED,
                "ats_platform": detection.platform.value,
            }
        # ─────────────────────────────────────────────────────────────────

        # Extract job details via LLM (only reached for valid pages)
        job_info = await llm_service.extract_job_details(state["job_url"], page_text)

        # Validate the LLM-extracted description too — the LLM sometimes returns
        # placeholder text like "not provided" when the page is a JS-heavy SPA
        # whose body text was navigation/chrome only (e.g. Workday before login).
        extracted_desc = job_info.get("description", "")
        if _is_valid_job_description(extracted_desc):
            final_description = extracted_desc
        elif _is_valid_job_description(page_text):
            # LLM extraction failed but raw page text is fine — use it directly
            logger.warning(
                f"[Agent] LLM returned thin/invalid description for {state['job_url']} "
                "— falling back to raw page text"
            )
            final_description = page_text[:5000]
        else:
            # Both LLM extraction and raw page text are bad — fail the job
            error_msg = (
                f"Could not extract a valid job description from {state['job_url']} "
                f"(LLM returned: '{extracted_desc[:80]}')"
            )
            logger.warning(f"[Agent] {error_msg}")
            await _log(
                state["job_id"], "fetch_job_details",
                "Extracted description invalid — skipping",
                {"url": state["job_url"], "extracted": extracted_desc[:120]},
            )
            return {
                **state,
                "error": error_msg,
                "status": JobStatus.FAILED,
                "ats_platform": detection.platform.value,
                "company": job_info.get("company", "Unknown"),
                "title": job_info.get("title", "Unknown"),
            }

        await _log(state["job_id"], "fetch_job_details", "Job details extracted", job_info)

        return {
            **state,
            "job_description": final_description,
            "company": job_info.get("company", "Unknown"),
            "title": job_info.get("title", "Unknown"),
            "ats_platform": detection.platform.value,
            "status": JobStatus.IN_PROGRESS,
        }

    except Exception as e:
        logger.error(f"fetch_job_details error: {e}")
        return {**state, "error": str(e), "status": JobStatus.FAILED}


async def tailor_resume(state: JobAgentState) -> JobAgentState:
    """Node 2: Tailor resume to the job description."""
    if state.get("error"):
        return state

    logger.info(f"[Agent] tailor_resume for job {state['job_id']}")

    try:
        # Create a minimal job object for resume service
        class _Job:
            id = state["job_id"]
            job_description = state["job_description"]

        path = await resume_service.tailor_and_generate(state["candidate_profile"], _Job())
        await _log(state["job_id"], "tailor_resume", f"Tailored resume saved: {path}")

        return {**state, "tailored_resume_path": path}

    except Exception as e:
        logger.error(f"tailor_resume error: {e}")
        return {**state, "error": str(e), "status": JobStatus.FAILED}


async def generate_cover_letter(state: JobAgentState) -> JobAgentState:
    """Node 3: Generate a cover letter."""
    if state.get("error"):
        return state

    logger.info(f"[Agent] generate_cover_letter for job {state['job_id']}")

    try:
        cover_letter = await llm_service.generate_cover_letter(
            candidate_profile=state["candidate_profile"],
            job_description=state["job_description"],
            company=state["company"],
            title=state["title"],
        )
        await _log(state["job_id"], "generate_cover_letter", "Cover letter generated")

        return {**state, "cover_letter": cover_letter}

    except Exception as e:
        logger.error(f"generate_cover_letter error: {e}")
        return {**state, "error": str(e), "status": JobStatus.FAILED}


async def fill_and_submit(state: JobAgentState) -> JobAgentState:
    """
    Node 4: Open browser, fill form, submit.

    ── fix (indirect) ────────────────────────────────────────────────
    BrowserService.start() now normalises the BROWSERLESS_URL to a proper
    WebSocket endpoint before connecting, so this node no longer fails with
    the HTTP-404 Playwright connection error.

    ── Agent log fix ─────────────────────────────────────────────────────────
    fill_form and submit are now logged as distinct steps so they appear in
    agent_logs. Previously the entire browser flow was a single
    'fill_and_submit' entry, making it impossible to tell whether the agent
    reached form-filling or only the browser launch.
    ─────────────────────────────────────────────────────────────────────────
    """
    if state.get("error"):
        return state

    logger.info(f"[Agent] fill_and_submit for job {state['job_id']}")

    browser_svc = BrowserService()

    try:
        await browser_svc.start()

        # Build mock job object
        class _Job:
            id = state["job_id"]
            url = state["job_url"]
            job_description = state["job_description"]

        result = await browser_svc.apply_to_job(
            job=_Job(),
            candidate_profile=state["candidate_profile"],
            tailored_resume_path=state["tailored_resume_path"],
            cover_letter=state["cover_letter"],
        )

        # ── Log fill_form and submit as separate steps ────────────────────
        # Always log fill_form once we get a result back from apply_to_job,
        # regardless of success/failure — the form-filling step was reached.
        # Previously the condition `result.get("error") not in (None, "HITL_TIMEOUT")`
        # was inverted, so fill_form was only logged on error, not on success.
        await _log(
            state["job_id"],
            "fill_form",
            "Form fields populated",
            {"unanswered": result.get("unanswered_fields", {})},
        )

        if result.get("success"):
            await _log(state["job_id"], "submit", "Application submitted successfully")
        # ─────────────────────────────────────────────────────────────────

        await _log(state["job_id"], "fill_and_submit", "Browser automation complete", result)

        if result.get("backlog"):
            return {
                **state,
                "status": JobStatus.BACKLOG,
                "unanswered_fields": result.get("unanswered_fields", {}),
                "error": "HITL_TIMEOUT",
            }
        elif not result.get("success"):
            return {
                **state,
                "status": JobStatus.FAILED,
                "error": result.get("error", "Unknown browser error"),
                "unanswered_fields": result.get("unanswered_fields", {}),
            }
        else:
            return {
                **state,
                "status": JobStatus.APPLIED,
                "unanswered_fields": result.get("unanswered_fields", {}),
            }

    except Exception as e:
        logger.error(f"fill_and_submit error: {e}")
        return {**state, "error": str(e), "status": JobStatus.FAILED}

    finally:
        await browser_svc.stop()


async def log_result(state: JobAgentState) -> JobAgentState:
    """Node 5: Persist final job status to DB."""
    logger.info(f"[Agent] log_result for job {state['job_id']} → {state['status']}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == state["job_id"]))
        job: Job = result.scalar_one_or_none()

        if job:
            job.status = state["status"]
            job.company = state.get("company", job.company)
            job.title = state.get("title", job.title)
            job.job_description = state.get("job_description", job.job_description)
            job.ats_platform = state.get("ats_platform", job.ats_platform)
            job.tailored_resume_path = state.get("tailored_resume_path", job.tailored_resume_path)
            job.cover_letter = state.get("cover_letter", job.cover_letter)
            job.failure_reason = state.get("error")
            job.unanswered_fields = state.get("unanswered_fields", {})
            if state["status"] == JobStatus.APPLIED:
                job.applied_at = datetime.utcnow()

            await db.commit()

        # Save new HITL custom answers
        new_answers = state.get("hitl_new_answers", {})
        for key, answer in new_answers.items():
            ca = CustomAnswer(
                candidate_id=state["candidate_id"],
                question_key=key,
                answer=answer,
                description="Auto-saved from HITL response",
            )
            db.add(ca)
        if new_answers:
            await db.commit()

    await _log(state["job_id"], "log_result", f"Job {state['job_id']} → {state['status']}")

    return state


# Routing Functions

def should_continue_after_fetch(state: JobAgentState) -> str:
    if state.get("error"):
        return "log_result"
    return "tailor_resume"


def should_continue_after_tailor(state: JobAgentState) -> str:
    if state.get("error"):
        return "log_result"
    return "generate_cover_letter"


def should_continue_after_cover(state: JobAgentState) -> str:
    if state.get("error"):
        return "log_result"
    return "fill_and_submit"


# Build Graph

def build_job_agent_graph():
    workflow = StateGraph(JobAgentState)

    workflow.add_node("fetch_job_details", fetch_job_details)
    workflow.add_node("tailor_resume", tailor_resume)
    workflow.add_node("generate_cover_letter", generate_cover_letter)
    workflow.add_node("fill_and_submit", fill_and_submit)
    workflow.add_node("log_result", log_result)

    workflow.set_entry_point("fetch_job_details")

    workflow.add_conditional_edges("fetch_job_details", should_continue_after_fetch)
    workflow.add_conditional_edges("tailor_resume", should_continue_after_tailor)
    workflow.add_conditional_edges("generate_cover_letter", should_continue_after_cover)
    workflow.add_edge("fill_and_submit", "log_result")
    workflow.add_edge("log_result", END)

    return workflow.compile()


job_agent_graph = build_job_agent_graph()


# Runner

async def run_job_agent(job_id: str, candidate_profile: dict):
    """Run the full agent pipeline for one job."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job: Job = result.scalar_one_or_none()
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        job.status = JobStatus.IN_PROGRESS
        job.started_at = datetime.utcnow()
        await db.commit()

    initial_state: JobAgentState = {
        "job_id": job_id,
        "candidate_id": candidate_profile["id"],
        "candidate_profile": candidate_profile,
        "job_url": job.url,
        "job_description": job.job_description or "",
        "company": job.company or "",
        "title": job.title or "",
        "ats_platform": job.ats_platform or ATSPlatform.UNKNOWN,
        "tailored_resume_path": "",
        "cover_letter": "",
        "unanswered_fields": {},
        "error": None,
        "status": JobStatus.IN_PROGRESS,
        "hitl_new_answers": {},
    }

    try:
        final_state = await job_agent_graph.ainvoke(initial_state)
        logger.info(f"Job {job_id} finished with status: {final_state['status']}")
        return final_state
    except Exception as e:
        logger.error(f"Agent pipeline error for job {job_id}: {e}")
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = JobStatus.FAILED
                job.failure_reason = str(e)
                await db.commit()


# Queue Runner

async def run_queue(candidate_id: str, candidate_profile: dict):
    """
    Process all queued jobs for a candidate one by one.
    On HITL timeout → job goes to backlog, agent continues to next.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job).where(
                Job.candidate_id == candidate_id,
                Job.status == JobStatus.QUEUED,
            ).order_by(Job.created_at)
        )
        jobs = result.scalars().all()

    logger.info(f"Starting queue: {len(jobs)} jobs for candidate {candidate_id}")

    for job in jobs:
        logger.info(f"Processing job {job.id}: {job.url}")
        await run_job_agent(job.id, candidate_profile)
        await asyncio.sleep(2)  # Brief pause between jobs

    logger.info("Queue processing complete.")


# Helpers

async def _log(job_id: str, step: str, message: str, data: dict = None):
    """Persist an agent log entry."""
    try:
        async with AsyncSessionLocal() as db:
            log = AgentLog(job_id=job_id, step=step, message=message, data=data)
            db.add(log)
            await db.commit()
    except Exception as e:
        logger.warning(f"Log write failed: {e}")