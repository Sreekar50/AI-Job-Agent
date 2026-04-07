"""Tests for ATS detection service."""
import pytest
from backend.services.ats_detector import ATSDetector, ATSPlatform


@pytest.fixture
def detector():
    return ATSDetector()


@pytest.mark.parametrize("url,expected_platform", [
    ("https://stripe.greenhouse.io/jobs/5988760003", ATSPlatform.GREENHOUSE),
    ("https://boards.greenhouse.io/anthropic/jobs/4020305008", ATSPlatform.GREENHOUSE),
    ("https://jobs.lever.co/scale-ai/c06a9d80", ATSPlatform.LEVER),
    ("https://stripe.myworkdayjobs.com/en-US/Jobs/job/123", ATSPlatform.WORKDAY),
    ("https://www.linkedin.com/jobs/view/12345678", ATSPlatform.LINKEDIN),
    ("https://careers.icims.com/jobs/12345/job", ATSPlatform.ICIMS),
    ("https://randomcompany.com/careers/open-roles/swe", ATSPlatform.UNKNOWN),
])
def test_url_detection(detector, url, expected_platform):
    result = detector.detect_from_url(url)
    assert result.platform == expected_platform


def test_url_detection_confidence(detector):
    result = detector.detect_from_url("https://boards.greenhouse.io/company/jobs/123")
    assert result.confidence == "url_pattern"
    assert result.platform == ATSPlatform.GREENHOUSE


def test_unknown_url(detector):
    result = detector.detect_from_url("https://careers.someunknowncompany.io/jobs/123")
    assert result.platform == ATSPlatform.UNKNOWN
