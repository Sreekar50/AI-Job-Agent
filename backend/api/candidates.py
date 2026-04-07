"""Candidates API — CRUD for candidate profiles, skills, work history, custom answers."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Candidate, WorkExperience, Education, Skill, CustomAnswer

router = APIRouter()


# Pydantic Schemas

class WorkExperienceIn(BaseModel):
    company: str
    title: str
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    description: Optional[str] = None
    technologies: list[str] = []

class EducationIn(BaseModel):
    institution: str
    degree: str
    field_of_study: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    gpa: Optional[str] = None

class SkillIn(BaseModel):
    name: str
    category: Optional[str] = None
    proficiency: Optional[str] = None

class CustomAnswerIn(BaseModel):
    question_key: str
    answer: str
    description: Optional[str] = None

class CandidateCreate(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    resume_path: Optional[str] = None
    summary: Optional[str] = None
    years_of_experience: Optional[int] = None
    work_experiences: list[WorkExperienceIn] = []
    educations: list[EducationIn] = []
    skills: list[SkillIn] = []
    custom_answers: list[CustomAnswerIn] = []


# Helpers

async def get_candidate_or_404(candidate_id: str, db: AsyncSession) -> Candidate:
    result = await db.execute(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            selectinload(Candidate.work_experiences),
            selectinload(Candidate.educations),
            selectinload(Candidate.skills),
            selectinload(Candidate.custom_answers),
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def candidate_to_profile_dict(c: Candidate) -> dict:
    return {
        "id": c.id,
        "full_name": c.full_name,
        "email": c.email,
        "phone": c.phone,
        "location": c.location,
        "linkedin_url": c.linkedin_url,
        "github_url": c.github_url,
        "portfolio_url": c.portfolio_url,
        "resume_path": c.resume_path,
        "summary": c.summary,
        "years_of_experience": c.years_of_experience,
        "work_experiences": [
            {
                "company": w.company,
                "title": w.title,
                "location": w.location,
                "start_date": w.start_date,
                "end_date": w.end_date,
                "is_current": w.is_current,
                "description": w.description,
                "technologies": w.technologies or [],
            }
            for w in c.work_experiences
        ],
        "educations": [
            {
                "institution": e.institution,
                "degree": e.degree,
                "field_of_study": e.field_of_study,
                "start_year": e.start_year,
                "end_year": e.end_year,
                "gpa": e.gpa,
            }
            for e in c.educations
        ],
        "skills": [{"name": s.name, "category": s.category, "proficiency": s.proficiency} for s in c.skills],
        "custom_answers": [{"question_key": qa.question_key, "answer": qa.answer} for qa in c.custom_answers],
    }


# Routes

@router.post("", status_code=201)
async def create_candidate(data: CandidateCreate, db: AsyncSession = Depends(get_db)):
    candidate = Candidate(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        location=data.location,
        linkedin_url=data.linkedin_url,
        github_url=data.github_url,
        portfolio_url=data.portfolio_url,
        resume_path=data.resume_path,
        summary=data.summary,
        years_of_experience=data.years_of_experience,
    )
    db.add(candidate)
    await db.flush()

    for w in data.work_experiences:
        db.add(WorkExperience(candidate_id=candidate.id, **w.model_dump()))
    for e in data.educations:
        db.add(Education(candidate_id=candidate.id, **e.model_dump()))
    for s in data.skills:
        db.add(Skill(candidate_id=candidate.id, **s.model_dump()))
    for qa in data.custom_answers:
        db.add(CustomAnswer(candidate_id=candidate.id, **qa.model_dump()))

    await db.commit()
    return {"id": candidate.id, "message": "Candidate created"}


@router.get("")
async def list_candidates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Candidate))
    candidates = result.scalars().all()
    return [c.to_dict() for c in candidates]


@router.get("/{candidate_id}")
async def get_candidate(candidate_id: str, db: AsyncSession = Depends(get_db)):
    candidate = await get_candidate_or_404(candidate_id, db)
    return candidate_to_profile_dict(candidate)


@router.patch("/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    candidate = await get_candidate_or_404(candidate_id, db)
    allowed = {"full_name","email","phone","location","linkedin_url","github_url","portfolio_url","resume_path","summary","years_of_experience"}
    for key, val in data.items():
        if key in allowed:
            setattr(candidate, key, val)
    await db.commit()
    return {"message": "Updated"}


@router.post("/{candidate_id}/custom-answers", status_code=201)
async def add_custom_answer(candidate_id: str, data: CustomAnswerIn, db: AsyncSession = Depends(get_db)):
    """
    Add a custom answer to the candidate's profile.
    Automatically picked up on next agent run — no code changes needed.
    """
    await get_candidate_or_404(candidate_id, db)

    # Upsert — update if key exists
    result = await db.execute(
        select(CustomAnswer).where(
            CustomAnswer.candidate_id == candidate_id,
            CustomAnswer.question_key == data.question_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.answer = data.answer
        existing.description = data.description
    else:
        db.add(CustomAnswer(candidate_id=candidate_id, **data.model_dump()))

    await db.commit()
    return {"message": f"Custom answer '{data.question_key}' saved"}


@router.get("/{candidate_id}/custom-answers")
async def list_custom_answers(candidate_id: str, db: AsyncSession = Depends(get_db)):
    await get_candidate_or_404(candidate_id, db)
    result = await db.execute(
        select(CustomAnswer).where(CustomAnswer.candidate_id == candidate_id)
    )
    answers = result.scalars().all()
    return [{"key": a.question_key, "answer": a.answer, "description": a.description} for a in answers]


@router.delete("/{candidate_id}/custom-answers/{key}")
async def delete_custom_answer(candidate_id: str, key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CustomAnswer).where(
            CustomAnswer.candidate_id == candidate_id,
            CustomAnswer.question_key == key,
        )
    )
    ca = result.scalar_one_or_none()
    if not ca:
        raise HTTPException(404, "Custom answer not found")
    await db.delete(ca)
    await db.commit()
    return {"message": "Deleted"}
