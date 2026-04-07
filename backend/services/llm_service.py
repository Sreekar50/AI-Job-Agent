"""
LLM Service — Groq (LangChain)

Handles:
- Resume tailoring
- Cover letter generation
- Form field inference
- Confidence scoring for HITL decisions
"""
import json
from typing import Any, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from backend.utils.config import settings


# Description quality helpers

_MIN_USEFUL_DESCRIPTION_LENGTH = 200  # chars — below this we treat JD as thin


def _description_is_thin(description: str) -> bool:
    """Return True when the job description is too short to be useful."""
    return not description or len(description.strip()) < _MIN_USEFUL_DESCRIPTION_LENGTH


# LLM Service 

class LLMService:
    def __init__(self):
        self.llm = ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            max_tokens=4096,
            temperature=0.3,
        )

    def _build_candidate_context(self, candidate_profile: dict) -> str:
        """Build a rich text context from candidate profile for the LLM."""
        ctx = f"""
CANDIDATE PROFILE:
Name: {candidate_profile.get('full_name')}
Email: {candidate_profile.get('email')}
Phone: {candidate_profile.get('phone')}
Location: {candidate_profile.get('location')}
LinkedIn: {candidate_profile.get('linkedin_url', 'N/A')}
GitHub: {candidate_profile.get('github_url', 'N/A')}
Years of Experience: {candidate_profile.get('years_of_experience', 'N/A')}
Summary: {candidate_profile.get('summary', '')}

WORK EXPERIENCE:
"""
        for exp in candidate_profile.get("work_experiences", []):
            ctx += f"""
- {exp['title']} at {exp['company']} ({exp.get('start_date','?')} – {exp.get('end_date','Present')})
  {exp.get('description', '')}
  Technologies: {', '.join(exp.get('technologies', []))}
"""

        ctx += "\nEDUCATION:\n"
        for edu in candidate_profile.get("educations", []):
            ctx += f"- {edu['degree']} in {edu.get('field_of_study','')} from {edu['institution']} ({edu.get('end_year','')})\n"

        ctx += "\nSKILLS:\n"
        skills = candidate_profile.get("skills", [])
        ctx += ", ".join([s["name"] for s in skills])

        ctx += "\n\nCUSTOM ANSWERS (pre-configured form answers):\n"
        for qa in candidate_profile.get("custom_answers", []):
            ctx += f"- {qa['question_key']}: {qa['answer']}\n"

        return ctx

    async def tailor_resume(self, candidate_profile: dict, job_description: str) -> str:
        """
        Generate a tailored resume summary/bullet points for the job.

        ── fix ──────────────────────────────────────────────────────
        When the job description is thin (short, vague, or missing), the
        prompt tells the LLM to write a strong general-purpose resume that
        highlights the candidate's best work instead of trying to match
        keywords that don't exist. This avoids producing a useless or
        hallucinated tailoring.
        ─────────────────────────────────────────────────────────────────────
        """
        logger.info("Tailoring resume with LLM...")
        candidate_ctx = self._build_candidate_context(candidate_profile)

        if _description_is_thin(job_description):
            logger.warning("Job description is thin — generating strong general-purpose resume")
            user_content = f"""
{candidate_ctx}

NOTE: No detailed job description is available for this role.
Write a strong, general-purpose software engineering resume that best represents
this candidate's experience and skills. Highlight breadth and depth rather than
trying to keyword-match a specific role.
"""
        else:
            user_content = f"""
{candidate_ctx}

JOB DESCRIPTION:
{job_description}

Please tailor this resume to best match this job description. Prioritize matching required skills and experience.
"""

        messages = [
            SystemMessage(content="""You are an expert resume writer.
Your task is to tailor the candidate's resume to match the job description.
Highlight relevant experience, reword bullet points to match job keywords,
and ensure ATS keyword alignment. Be specific and quantitative.
Return the tailored resume as clean plain text with sections:
SUMMARY, EXPERIENCE, EDUCATION, SKILLS."""),
            HumanMessage(content=user_content),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content

    async def generate_cover_letter(
        self, candidate_profile: dict, job_description: str, company: str, title: str
    ) -> str:
        """
        Generate a personalized cover letter.

        ── fix ──────────────────────────────────────────────────────
        When the job description is thin (e.g. the page was a 404 that got
        past an older validation step, or the description field is nearly
        empty), the LLM is now instructed to:
          • Acknowledge the limited information it has
          • Focus on the candidate's strongest, most transferable achievements
          • Avoid fabricating company-specific details it cannot know
          • Still address the company by name if one is available

        This eliminates the generic "As a seasoned software engineer with a
        passion…" opener that appeared on all jobs with thin descriptions,
        because the old prompt had no fallback and the LLM defaulted to a
        generic template.
        ─────────────────────────────────────────────────────────────────────
        """
        logger.info(f"Generating cover letter for {title} at {company}...")
        candidate_ctx = self._build_candidate_context(candidate_profile)

        company_label = company if company and company.lower() != "unknown" else "this company"
        title_label = title if title and title.lower() != "unknown" else "this role"

        if _description_is_thin(job_description):
            logger.warning(
                f"Job description is thin for {title_label} at {company_label} — "
                "writing achievement-focused cover letter"
            )
            system_prompt = """You are an expert cover letter writer.
Write a compelling, personalized cover letter (3 short paragraphs, ~250 words).
A full job description is NOT available, so:
- Paragraph 1: Express genuine interest in the company/role; do NOT fabricate company-specific details you don't know
- Paragraph 2: Highlight the candidate's top 2-3 concrete achievements (use numbers from their experience)
- Paragraph 3: Call to action — invite a conversation
Keep the tone confident and specific to the candidate's actual experience.

FORBIDDEN OPENERS — never start with any of these or their variants:
  "As a seasoned..."
  "As an experienced..."
  "As a passionate..."
  "As a software engineer with..."
  "I am excited to apply..."
  "I am writing to express..."

Open with a concrete achievement or a specific reason you are drawn to the company/role.
Example: "Building payment infrastructure that handled $500B in transactions is the kind of
systems challenge that defines a career — and it's exactly what drew me to [Company]." """
            user_content = f"""
{candidate_ctx}

COMPANY: {company_label}
ROLE: {title_label}

Note: No detailed job description is available. Write based on the candidate's profile alone.
"""
        else:
            system_prompt = """You are an expert cover letter writer.
Write a compelling, personalized cover letter (3 short paragraphs, ~250 words).
- Paragraph 1: Hook + why this specific company/role
- Paragraph 2: Top 2-3 relevant achievements matching the JD (use numbers)
- Paragraph 3: Call to action
Avoid clichés and generic AI opener phrases. Be specific. Sound human.

FORBIDDEN OPENERS — never start with any of these or their variants:
  "As a seasoned..."
  "As an experienced..."
  "As a passionate..."
  "As a software engineer with..."
  "I am excited to apply..."
  "I am writing to express..."
  "I was thrilled to come across..."

GOOD OPENER PATTERN: Open with something concrete — a specific achievement,
a named product, a data point from the JD, or something distinctive about
the company. Example: "Stripe's mission to increase GDP of the internet is
exactly the kind of infrastructure challenge I've spent the last four years
solving at scale."

Start with something specific to THIS company or THIS role."""
            user_content = f"""
{candidate_ctx}

COMPANY: {company_label}
ROLE: {title_label}
JOB DESCRIPTION:
{job_description}

Write the cover letter.
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content

    async def infer_form_field(
        self,
        field_label: str,
        field_type: str,
        field_options: Optional[list],
        candidate_profile: dict,
        job_description: str,
    ) -> dict:
        """
        Infer an answer for a form field using LLM.

        Returns:
            {
                "answer": "...",
                "confidence": 0.0-1.0,
                "should_escalate": bool,  # True if confidence < 0.6
                "reasoning": "..."
            }
        """
        candidate_ctx = self._build_candidate_context(candidate_profile)
        options_str = f"\nAllowed options: {json.dumps(field_options)}" if field_options else ""

        messages = [
SystemMessage(content="""\
You are filling out a job application form on behalf of the candidate.
Given a form field and full candidate context, provide the best answer.
Respond ONLY with valid JSON in this exact format:
{
  "answer": "the answer string",
  "confidence": 0.85,
  "should_escalate": false,
  "reasoning": "brief explanation"
}
- confidence: 0.0 to 1.0
- should_escalate: true for ANY of these: salary/compensation questions,
  relocation decisions, equity preferences, current CTC, visa sponsorship
  details beyond yes/no, or anything requiring a specific number the
  candidate hasn't pre-configured. Also escalate if confidence < 0.6.
- For dropdown fields, answer must exactly match one of the allowed options
- For yes/no fields, answer must be "Yes" or "No"
- Never leave an answer blank if you can reasonably infer it\
"""),
            HumanMessage(content=f"""
{candidate_ctx}

JOB DESCRIPTION:
{job_description}

FORM FIELD:
Label: {field_label}
Type: {field_type}{options_str}

What should the candidate answer for this field?
"""),
        ]

        response = await self.llm.ainvoke(messages)

        try:
            # Strip markdown code fences if present
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content.strip())
            return result
        except (json.JSONDecodeError, IndexError):
            logger.error(f"LLM returned invalid JSON for field '{field_label}': {response.content}")
            return {
                "answer": "",
                "confidence": 0.0,
                "should_escalate": True,
                "reasoning": "LLM returned invalid response",
            }

    async def extract_job_details(self, job_url: str, page_text: str) -> dict:
        """
        Extract structured job info from raw page text.

        ──fix  ─────────────────────────────────────────────
        Returns a sentinel dict with description="" when the page text is too
        short to extract anything meaningful. The caller (fetch_job_details in
        job_agent.py) already validates the description before calling this
        method, so in practice this path is rarely hit. The guard is here as
        a defence-in-depth measure.
        ─────────────────────────────────────────────────────────────────────
        """
        if _description_is_thin(page_text):
            logger.warning(f"Page text too thin to extract job details from {job_url}")
            return {
                "company": "Unknown",
                "title": "Unknown",
                "description": "",
                "location": "",
                "job_type": "",
            }

        messages = [
            SystemMessage(content="""Extract job details from the page text.
Respond ONLY with valid JSON:
{
  "company": "Company Name",
  "title": "Job Title",
  "description": "Full job description text",
  "location": "City, State or Remote",
  "job_type": "Full-time"
}"""),
            HumanMessage(content=f"URL: {job_url}\n\nPage text:\n{page_text[:8000]}"),
        ]

        response = await self.llm.ainvoke(messages)
        try:
            content = response.content.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(content)
        except Exception:
            return {
                "company": "Unknown",
                "title": "Unknown",
                "description": page_text[:3000],
                "location": "",
                "job_type": "",
            }


llm_service = LLMService()