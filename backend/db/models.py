"""
Database models for the AI Job Application Agent.
Designed to be easy to extend — add columns freely.
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List

from sqlalchemy import (
    String, Text, DateTime, ForeignKey, JSON, Enum,
    Boolean, Integer, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from backend.db.database import Base


def gen_uuid():
    return str(uuid.uuid4())


# Enums

class JobStatus(str, PyEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    APPLIED = "applied"
    FAILED = "failed"
    BACKLOG = "backlog"        # HITL timeout — needs review


class ATSPlatform(str, PyEnum):
    WORKDAY = "workday"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    LINKEDIN = "linkedin"
    ICIMS = "icims"
    UNKNOWN = "unknown"


# Candidate

class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    github_url: Mapped[Optional[str]] = mapped_column(String(500))
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(500))
    resume_path: Mapped[Optional[str]] = mapped_column(String(500))  # local PDF path
    summary: Mapped[Optional[str]] = mapped_column(Text)
    years_of_experience: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    work_experiences: Mapped[List["WorkExperience"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    educations: Mapped[List["Education"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    skills: Mapped[List["Skill"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    custom_answers: Mapped[List["CustomAnswer"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship(back_populates="candidate")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "portfolio_url": self.portfolio_url,
            "resume_path": self.resume_path,
            "summary": self.summary,
            "years_of_experience": self.years_of_experience,
        }


class WorkExperience(Base):
    __tablename__ = "work_experiences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    start_date: Mapped[Optional[str]] = mapped_column(String(20))   # "2021-06"
    end_date: Mapped[Optional[str]] = mapped_column(String(20))     # "2024-01" or "Present"
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    technologies: Mapped[Optional[List]] = mapped_column(JSON, default=list)

    candidate: Mapped["Candidate"] = relationship(back_populates="work_experiences")


class Education(Base):
    __tablename__ = "educations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str] = mapped_column(String(255), nullable=False)
    field_of_study: Mapped[Optional[str]] = mapped_column(String(255))
    start_year: Mapped[Optional[int]] = mapped_column(Integer)
    end_year: Mapped[Optional[int]] = mapped_column(Integer)
    gpa: Mapped[Optional[str]] = mapped_column(String(10))

    candidate: Mapped["Candidate"] = relationship(back_populates="educations")


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100))  # "language", "framework", "tool"
    proficiency: Mapped[Optional[str]] = mapped_column(String(50))  # "expert", "proficient", "familiar"

    candidate: Mapped["Candidate"] = relationship(back_populates="skills")


class CustomAnswer(Base):
    """
    Key-value store for form questions not covered by the resume.
    Add a new entry at any time — auto-picked up on next run, no code changes.

    Examples:
      sponsorship_required → "No"
      notice_period        → "30 days"
      salary_expectation   → "120000"
      willing_to_relocate  → "Yes"
      how_heard_about_job  → "LinkedIn"
      demographic_gender   → "Prefer not to say"
      work_authorization   → "US Citizen"
    """
    __tablename__ = "custom_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)  # human-readable hint
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="custom_answers")


# Jobs

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    job_description: Mapped[Optional[str]] = mapped_column(Text)
    ats_platform: Mapped[str] = mapped_column(
        Enum(ATSPlatform), default=ATSPlatform.UNKNOWN
    )
    status: Mapped[str] = mapped_column(
        Enum(JobStatus), default=JobStatus.QUEUED, nullable=False
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    unanswered_fields: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    tailored_resume_path: Mapped[Optional[str]] = mapped_column(String(500))
    cover_letter: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="jobs")
    agent_logs: Mapped[List["AgentLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class AgentLog(Base):
    """Stores agent step logs for observability."""
    __tablename__ = "agent_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    step: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    job: Mapped["Job"] = relationship(back_populates="agent_logs")
