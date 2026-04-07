"""Tests for field resolution precedence chain."""
import pytest
from unittest.mock import AsyncMock, patch
from backend.services.field_resolver import FieldResolver


SAMPLE_PROFILE = {
    "id": "test-id",
    "full_name": "Alex Rivera",
    "email": "alex@example.com",
    "phone": "+1-415-555-0182",
    "location": "San Francisco, CA",
    "linkedin_url": "https://linkedin.com/in/alexrivera",
    "github_url": "https://github.com/alexrivera",
    "portfolio_url": "https://alexrivera.dev",
    "summary": "Backend engineer with 4 years experience.",
    "years_of_experience": 4,
    "work_experiences": [],
    "educations": [],
    "skills": [],
    "custom_answers": [
        {"question_key": "notice_period", "answer": "2 weeks"},
        {"question_key": "sponsorship_required", "answer": "No"},
        {"question_key": "salary_expectation", "answer": "165000"},
    ],
}


@pytest.fixture
def resolver():
    return FieldResolver(SAMPLE_PROFILE, "Software engineer role at Acme", "job-123")


def test_profile_email(resolver):
    answer = resolver.resolve_from_profile("Email Address")
    assert answer == "alex@example.com"


def test_profile_first_name(resolver):
    answer = resolver.resolve_from_profile("First Name")
    assert answer == "Alex"


def test_profile_last_name(resolver):
    answer = resolver.resolve_from_profile("Last Name")
    assert answer == "Rivera"


def test_profile_phone(resolver):
    answer = resolver.resolve_from_profile("Phone Number")
    assert answer == "+1-415-555-0182"


def test_profile_linkedin(resolver):
    answer = resolver.resolve_from_profile("LinkedIn Profile URL")
    assert answer == "https://linkedin.com/in/alexrivera"


def test_custom_answer_exact(resolver):
    answer = resolver.resolve_from_custom_answers("notice_period")
    assert answer == "2 weeks"


def test_custom_answer_fuzzy(resolver):
    answer = resolver.resolve_from_custom_answers("Do you require visa sponsorship?")
    assert answer == "No"


def test_custom_answer_salary(resolver):
    answer = resolver.resolve_from_custom_answers("What is your salary expectation?")
    assert answer == "165000"


def test_profile_takes_precedence(resolver):
    # Profile fields should match before custom answers
    answer = resolver.resolve_from_profile("email")
    assert answer == "alex@example.com"
