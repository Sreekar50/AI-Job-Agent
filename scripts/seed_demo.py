"""
Seed the database with a demo candidate and 6 job URLs across 3+ ATS platforms.
Run: python scripts/seed_demo.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import AsyncSessionLocal
from backend.db.models import (
    Candidate, WorkExperience, Education, Skill, CustomAnswer, Job, JobStatus
)
from loguru import logger


DEMO_CANDIDATE = {
    "full_name": "Alex Rivera",
    "email": "alex.rivera.dev@gmail.com",
    "phone": "+1-415-555-0182",
    "location": "San Francisco, CA",
    "linkedin_url": "https://linkedin.com/in/alexrivera-dev",
    "github_url": "https://github.com/alexrivera-dev",
    "portfolio_url": "https://alexrivera.dev",
    "resume_path": "demo/resumes/alex_rivera_resume.pdf",
    "summary": (
        "Mid-level software engineer with 4 years of experience building scalable "
        "backend systems and APIs. Proficient in Python, FastAPI, Node.js, PostgreSQL, "
        "and cloud infrastructure (AWS, GCP). Passionate about developer tooling, "
        "distributed systems, and clean architecture. Open-source contributor."
    ),
    "years_of_experience": 4,
}

DEMO_WORK_EXPERIENCES = [
    {
        "company": "Stripe",
        "title": "Software Engineer II",
        "location": "San Francisco, CA",
        "start_date": "2022-06",
        "end_date": "Present",
        "is_current": True,
        "description": (
            "Built and maintained payment processing microservices handling 50K+ req/min. "
            "Designed async event-driven pipelines using Kafka. Reduced API latency by 35% "
            "via query optimization and Redis caching. Mentored 2 junior engineers."
        ),
        "technologies": ["Python", "FastAPI", "PostgreSQL", "Kafka", "Redis", "AWS", "Docker", "Kubernetes"],
    },
    {
        "company": "Lyft",
        "title": "Software Engineer",
        "location": "San Francisco, CA",
        "start_date": "2020-08",
        "end_date": "2022-05",
        "is_current": False,
        "description": (
            "Developed driver-side APIs for the Lyft Driver app. Implemented real-time "
            "location tracking with WebSockets. Improved driver matching algorithm reducing "
            "wait times by 18%. Built CI/CD pipelines with GitHub Actions."
        ),
        "technologies": ["Python", "Go", "Node.js", "PostgreSQL", "Redis", "GCP", "Terraform"],
    },
    {
        "company": "TechStart Inc.",
        "title": "Junior Software Engineer",
        "location": "Austin, TX",
        "start_date": "2019-06",
        "end_date": "2020-07",
        "is_current": False,
        "description": (
            "Full-stack web development for B2B SaaS product. Built REST APIs with "
            "Django and React frontend. Integrated third-party payment and email services."
        ),
        "technologies": ["Python", "Django", "React", "MySQL", "AWS EC2"],
    },
]

DEMO_EDUCATIONS = [
    {
        "institution": "University of Texas at Austin",
        "degree": "Bachelor of Science",
        "field_of_study": "Computer Science",
        "start_year": 2015,
        "end_year": 2019,
        "gpa": "3.7",
    }
]

DEMO_SKILLS = [
    {"name": "Python", "category": "language", "proficiency": "expert"},
    {"name": "JavaScript", "category": "language", "proficiency": "proficient"},
    {"name": "Go", "category": "language", "proficiency": "familiar"},
    {"name": "FastAPI", "category": "framework", "proficiency": "expert"},
    {"name": "Django", "category": "framework", "proficiency": "proficient"},
    {"name": "Node.js", "category": "framework", "proficiency": "proficient"},
    {"name": "React", "category": "framework", "proficiency": "familiar"},
    {"name": "PostgreSQL", "category": "database", "proficiency": "expert"},
    {"name": "Redis", "category": "database", "proficiency": "proficient"},
    {"name": "MongoDB", "category": "database", "proficiency": "familiar"},
    {"name": "Docker", "category": "tool", "proficiency": "expert"},
    {"name": "Kubernetes", "category": "tool", "proficiency": "proficient"},
    {"name": "AWS", "category": "cloud", "proficiency": "proficient"},
    {"name": "GCP", "category": "cloud", "proficiency": "familiar"},
    {"name": "Kafka", "category": "tool", "proficiency": "proficient"},
    {"name": "Terraform", "category": "tool", "proficiency": "familiar"},
    {"name": "Git", "category": "tool", "proficiency": "expert"},
    {"name": "Linux", "category": "tool", "proficiency": "expert"},
]

DEMO_CUSTOM_ANSWERS = [
    {"question_key": "sponsorship_required", "answer": "No", "description": "US work authorization"},
    {"question_key": "work_authorization", "answer": "US Citizen", "description": "Citizenship status"},
    {"question_key": "notice_period", "answer": "2 weeks", "description": "Standard notice period"},
    # {"question_key": "salary_expectation", "answer": "165000", "description": "Base salary expectation USD"},
    # {"question_key": "willing_to_relocate", "answer": "No", "description": "Prefers remote or SF Bay Area"},
    {"question_key": "remote_preference", "answer": "Remote or Hybrid", "description": "Work arrangement preference"},
    {"question_key": "how_heard_about_job", "answer": "LinkedIn", "description": "Job discovery source"},
    {"question_key": "demographic_gender", "answer": "Prefer not to say", "description": "EEO demographic"},
    {"question_key": "demographic_ethnicity", "answer": "Prefer not to say", "description": "EEO demographic"},
    {"question_key": "veteran_status", "answer": "I am not a protected veteran", "description": "Veteran status"},
    {"question_key": "disability_status", "answer": "I do not have a disability", "description": "Disability status"},
    {"question_key": "highest_education", "answer": "Bachelor's Degree", "description": "Education level"},
    {"question_key": "cover_letter_summary", "answer": (
        "I'm a backend-focused software engineer with 4 years of experience at Stripe and Lyft, "
        "where I built high-throughput distributed systems. I'm looking for roles where I can "
        "work on challenging technical problems with a collaborative team."
    ), "description": "Generic cover letter opening"},
    {"question_key": "linkedin_profile", "answer": "https://linkedin.com/in/alexrivera-dev", "description": "LinkedIn URL"},
    {"question_key": "github_profile", "answer": "https://github.com/alexrivera-dev", "description": "GitHub URL"},
    {"question_key": "years_of_experience", "answer": "4", "description": "Years of professional experience"},
    {"question_key": "available_start_date", "answer": "2 weeks from offer acceptance", "description": "Availability"},
]

# 6 real job URLs across Greenhouse, Lever, Workday, LinkedIn, iCIMS
DEMO_JOB_URLS = [
    # Greenhouse
    "https://boards.greenhouse.io/anthropic/jobs/4952079008",
    "https://job-boards.greenhouse.io/redwoodsoftware/jobs/4205436009",
    # Lever
    "https://jobs.lever.co/welocalize/92095fc9-4733-4f4d-9a77-26778b97e850",
    # Workday
    "https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/Software-Development-Engineer---Hiredscore_JR-0103627?source=Careers_Website",
    # LinkedIn
    "https://www.linkedin.com/jobs/view/4388252206/",
    # iCIMS / generic
    "https://careers.icims.com/careers-home/jobs/6427",
]


async def seed():
    logger.info("Seeding demo candidate...")
    async with AsyncSessionLocal() as db:
        # Create candidate
        candidate = Candidate(**DEMO_CANDIDATE)
        db.add(candidate)
        await db.flush()
        candidate_id = candidate.id
        logger.info(f"Created candidate: {candidate_id}")

        # Work experiences
        for we in DEMO_WORK_EXPERIENCES:
            db.add(WorkExperience(candidate_id=candidate_id, **we))

        # Education
        for edu in DEMO_EDUCATIONS:
            db.add(Education(candidate_id=candidate_id, **edu))

        # Skills
        for skill in DEMO_SKILLS:
            db.add(Skill(candidate_id=candidate_id, **skill))

        # Custom answers
        for qa in DEMO_CUSTOM_ANSWERS:
            db.add(CustomAnswer(candidate_id=candidate_id, **qa))

        # Jobs
        for url in DEMO_JOB_URLS:
            db.add(Job(candidate_id=candidate_id, url=url, status=JobStatus.QUEUED))

        await db.commit()
        logger.info(f"Seeded {len(DEMO_JOB_URLS)} jobs into queue.")

    logger.info(f"\n{'='*50}")
    logger.info(f"Demo seed complete!")
    logger.info(f"Candidate ID: {candidate_id}")
    logger.info(f"Run the agent: python scripts/run_agent.py {candidate_id}")
    logger.info(f"{'='*50}\n")
    return candidate_id


if __name__ == "__main__":
    asyncio.run(seed())
