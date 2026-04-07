"""
Tailors the candidate's resume to a specific job description using the LLM,
then generates a PDF for upload.
"""
import os
from pathlib import Path
from typing import Optional

from loguru import logger
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from backend.services.llm_service import llm_service


RESUMES_DIR = Path("demo/resumes")
TAILORED_DIR = Path("demo/tailored_resumes")


class ResumeService:

    def __init__(self):
        TAILORED_DIR.mkdir(parents=True, exist_ok=True)

    async def tailor_and_generate(
        self, candidate_profile: dict, job: object
    ) -> str:
        """
        Tailor resume to job and generate a PDF.
        Returns path to the tailored PDF.
        """
        logger.info(f"Tailoring resume for job {job.id}")

        tailored_text = await llm_service.tailor_resume(
            candidate_profile=candidate_profile,
            job_description=job.job_description or "",
        )

        output_path = TAILORED_DIR / f"{candidate_profile['id']}_{job.id}_resume.pdf"
        self._generate_pdf(tailored_text, candidate_profile, str(output_path))
        logger.info(f"Tailored resume saved: {output_path}")

        return output_path.as_posix()

    def _generate_pdf(self, tailored_text: str, profile: dict, output_path: str):
        """Generate a clean resume PDF from tailored text."""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=LETTER,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        elements = []

        # Header
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Normal"],
            fontSize=18,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            spaceAfter=4,
        )
        subheader_style = ParagraphStyle(
            "SubHeader",
            parent=styles["Normal"],
            fontSize=10,
            alignment=TA_CENTER,
            spaceAfter=12,
        )
        section_style = ParagraphStyle(
            "Section",
            parent=styles["Normal"],
            fontSize=12,
            fontName="Helvetica-Bold",
            spaceBefore=12,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            spaceAfter=4,
            leading=14,
        )

        # Name
        elements.append(Paragraph(profile.get("full_name", "Candidate"), header_style))

        # Contact info
        contact_parts = [
            profile.get("email", ""),
            profile.get("phone", ""),
            profile.get("location", ""),
            profile.get("linkedin_url", ""),
            profile.get("github_url", ""),
        ]
        contact_line = " | ".join([p for p in contact_parts if p])
        elements.append(Paragraph(contact_line, subheader_style))

        # Tailored content
        for line in tailored_text.split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 4))
                continue

            # Section headers (all caps or starts with common keywords)
            if (
                line.isupper()
                or line.startswith("SUMMARY")
                or line.startswith("EXPERIENCE")
                or line.startswith("EDUCATION")
                or line.startswith("SKILLS")
                or line.startswith("PROJECTS")
            ):
                elements.append(Paragraph(line, section_style))
            elif line.startswith("•") or line.startswith("-"):
                elements.append(Paragraph(line.replace("•", "•&nbsp;"), body_style))
            else:
                elements.append(Paragraph(line, body_style))

        doc.build(elements)


resume_service = ResumeService()
