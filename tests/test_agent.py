"""
Tests for the AI Job Application Agent

Run with: pytest tests/ -v
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


# ATS Detector Tests

class TestATSDetector:
    def setup_method(self):
        from backend.services.ats_detector import ATSDetector, ATSPlatform
        self.detector = ATSDetector()
        self.ATSPlatform = ATSPlatform

    def test_greenhouse_url_detection(self):
        result = self.detector.detect_from_url("https://boards.greenhouse.io/anthropic/jobs/123")
        assert result.platform == self.ATSPlatform.GREENHOUSE
        assert result.confidence == "url_pattern"

    def test_lever_url_detection(self):
        result = self.detector.detect_from_url("https://jobs.lever.co/scale-ai/abc123")
        assert result.platform == self.ATSPlatform.LEVER

    def test_workday_url_detection(self):
        result = self.detector.detect_from_url("https://amazon.wd5.myworkdayjobs.com/en-US/External_Posting")
        assert result.platform == self.ATSPlatform.WORKDAY

    def test_linkedin_url_detection(self):
        result = self.detector.detect_from_url("https://www.linkedin.com/jobs/view/3987654321")
        assert result.platform == self.ATSPlatform.LINKEDIN

    def test_unknown_url(self):
        result = self.detector.detect_from_url("https://careers.randomcompany.com/jobs/123")
        assert result.platform == self.ATSPlatform.UNKNOWN

    def test_icims_detection(self):
        result = self.detector.detect_from_url("https://careers.icims.com/jobs/1234")
        assert result.platform == self.ATSPlatform.ICIMS


# Field Resolver Tests

class TestFieldResolver:
    def setup_method(self):
        from backend.services.field_resolver import FieldResolver
        self.profile = {
            "id": "test-id",
            "full_name": "Arjun Mehta",
            "email": "arjun@example.com",
            "phone": "+1-415-555-0192",
            "location": "San Francisco, CA",
            "linkedin_url": "https://linkedin.com/in/arjunmehta",
            "github_url": "https://github.com/arjunmehta",
            "portfolio_url": "https://arjunmehta.dev",
            "summary": "Software Engineer with 4 years of experience.",
            "years_of_experience": 4,
            "work_experiences": [],
            "educations": [],
            "skills": [],
            "custom_answers": [
                {"question_key": "sponsorship_required", "answer": "No"},
                {"question_key": "notice_period", "answer": "2 weeks"},
                {"question_key": "salary_expectation", "answer": "130000"},
            ],
        }
        self.resolver = FieldResolver(
            candidate_profile=self.profile,
            job_description="Software Engineer role at a tech company",
            job_id="job-123",
        )

    def test_resolve_first_name(self):
        result = self.resolver.resolve_from_profile("First Name")
        assert result == "Arjun"

    def test_resolve_last_name(self):
        result = self.resolver.resolve_from_profile("Last Name")
        assert result == "Mehta"

    def test_resolve_full_name(self):
        result = self.resolver.resolve_from_profile("Full Name")
        assert result == "Arjun Mehta"

    def test_resolve_email(self):
        result = self.resolver.resolve_from_profile("Email Address")
        assert result == "arjun@example.com"

    def test_resolve_phone(self):
        result = self.resolver.resolve_from_profile("Phone Number")
        assert result == "+1-415-555-0192"

    def test_resolve_linkedin(self):
        result = self.resolver.resolve_from_profile("LinkedIn URL")
        assert "linkedin.com" in result

    def test_custom_answer_exact_match(self):
        result = self.resolver.resolve_from_custom_answers("sponsorship_required")
        assert result == "No"

    def test_custom_answer_fuzzy_match(self):
        result = self.resolver.resolve_from_custom_answers("Do you require visa sponsorship?")
        assert result == "No"

    def test_custom_answer_salary(self):
        result = self.resolver.resolve_from_custom_answers("salary expectation")
        assert result == "130000"

    def test_unknown_field_returns_none_from_profile(self):
        result = self.resolver.resolve_from_profile("some totally random field xyz")
        assert result is None


# HITL Manager Tests

class TestHITLManager:
    @pytest.mark.asyncio
    async def test_hitl_timeout(self):
        from backend.utils.hitl_manager import HITLManager
        manager = HITLManager()

        # Very short timeout for test
        import backend.utils.config as cfg
        original = cfg.settings.HITL_TIMEOUT_SECONDS
        cfg.settings.HITL_TIMEOUT_SECONDS = 1  # 1 second for test

        result = await manager.request_answer(
            job_id="test-job",
            field_label="Test Field",
            field_type="text",
        )

        cfg.settings.HITL_TIMEOUT_SECONDS = original
        assert result is None  # timeout returns None

    @pytest.mark.asyncio
    async def test_hitl_answer_submitted(self):
        from backend.utils.hitl_manager import HITLManager
        manager = HITLManager()

        import backend.utils.config as cfg
        original = cfg.settings.HITL_TIMEOUT_SECONDS
        cfg.settings.HITL_TIMEOUT_SECONDS = 5

        # Submit answer after brief delay
        async def submit_after_delay():
            await asyncio.sleep(0.5)
            manager.submit_answer("test-job-2", "My Answer")

        asyncio.create_task(submit_after_delay())
        result = await manager.request_answer(
            job_id="test-job-2",
            field_label="Test Field",
            field_type="text",
        )

        cfg.settings.HITL_TIMEOUT_SECONDS = original
        assert result == "My Answer"

    def test_submit_no_pending(self):
        from backend.utils.hitl_manager import HITLManager
        manager = HITLManager()
        success = manager.submit_answer("nonexistent-job", "answer")
        assert success is False

    def test_get_pending_returns_none_for_unknown(self):
        from backend.utils.hitl_manager import HITLManager
        manager = HITLManager()
        assert manager.get_pending("no-job") is None


# LLM Service Tests (mocked)

class TestLLMService:
    @pytest.mark.asyncio
    async def test_infer_field_returns_dict(self):
        from backend.services.llm_service import LLMService
        service = LLMService()

        mock_response = MagicMock()
        mock_response.content = '{"answer": "No", "confidence": 0.95, "should_escalate": false, "reasoning": "Standard answer"}'

        with patch.object(service.llm, "ainvoke", new_callable=AsyncMock, return_value=mock_response):
            result = await service.infer_form_field(
                field_label="Do you require visa sponsorship?",
                field_type="radio",
                field_options=["Yes", "No"],
                candidate_profile={
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "work_experiences": [],
                    "educations": [],
                    "skills": [],
                    "custom_answers": [],
                },
                job_description="Software Engineer role",
            )

        assert result["answer"] == "No"
        assert result["confidence"] == 0.95
        assert result["should_escalate"] is False

    @pytest.mark.asyncio
    async def test_tailor_resume(self):
        from backend.services.llm_service import LLMService
        service = LLMService()

        mock_response = MagicMock()
        mock_response.content = "SUMMARY\nTailored summary.\n\nEXPERIENCE\nJob at Company."

        with patch.object(service.llm, "ainvoke", new_callable=AsyncMock, return_value=mock_response):
            result = await service.tailor_resume(
                candidate_profile={
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "summary": "Original summary",
                    "work_experiences": [],
                    "educations": [],
                    "skills": [],
                    "custom_answers": [],
                },
                job_description="Python engineer needed",
            )

        assert "SUMMARY" in result
        assert "EXPERIENCE" in result


# API Route Tests

@pytest.mark.asyncio
async def test_health_endpoint():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_root_endpoint():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "AI Job Application Agent" in response.json()["message"]
