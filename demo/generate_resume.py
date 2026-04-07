"""
Generate a realistic-looking demo resume PDF for the seeded candidate.
"""
import os
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib import colors


RESUMES_DIR = Path("demo/resumes")


def generate_demo_resume(
    candidate_id: str,
    profile: dict,
    work_experiences: list,
    educations: list,
    skills: list,
) -> str:
    """Generate a professional resume PDF. Returns the file path."""
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESUMES_DIR / f"{candidate_id}_resume.pdf"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
    )

    styles = getSampleStyleSheet()
    NAVY = colors.HexColor("#1a2e4a")
    GRAY = colors.HexColor("#555555")
    LIGHT = colors.HexColor("#eeeeee")

    name_style = ParagraphStyle("Name", fontSize=22, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_CENTER, spaceAfter=2)
    contact_style = ParagraphStyle("Contact", fontSize=9, textColor=GRAY, alignment=TA_CENTER, spaceAfter=12)
    section_style = ParagraphStyle("Section", fontSize=11, fontName="Helvetica-Bold", textColor=NAVY, spaceBefore=12, spaceAfter=4)
    job_title_style = ParagraphStyle("JobTitle", fontSize=10, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=1)
    job_meta_style = ParagraphStyle("JobMeta", fontSize=9, textColor=GRAY, spaceAfter=3)
    body_style = ParagraphStyle("Body", fontSize=9, leading=13, spaceAfter=2)
    bullet_style = ParagraphStyle("Bullet", fontSize=9, leading=13, leftIndent=12, spaceAfter=1)

    elements = []

    # ── Header ──
    elements.append(Paragraph(profile["full_name"], name_style))
    contact = (
        f"{profile.get('email', '')} &nbsp;|&nbsp; {profile.get('phone', '')} &nbsp;|&nbsp; "
        f"{profile.get('location', '')} &nbsp;|&nbsp; "
        f"<a href='{profile.get('linkedin_url','')}'>{profile.get('linkedin_url','')}</a> &nbsp;|&nbsp; "
        f"<a href='{profile.get('github_url','')}'>{profile.get('github_url','')}</a>"
    )
    elements.append(Paragraph(contact, contact_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=6))

    # ── Summary ──
    elements.append(Paragraph("PROFESSIONAL SUMMARY", section_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(profile.get("summary", ""), body_style))

    # ── Experience ──
    elements.append(Paragraph("WORK EXPERIENCE", section_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT))

    for exp in work_experiences:
        end = exp.get("end_date", "Present") if not exp.get("is_current") else "Present"
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(f"<b>{exp['title']}</b> — {exp['company']}", job_title_style))
        elements.append(Paragraph(
            f"{exp.get('location', '')} &nbsp;|&nbsp; {exp.get('start_date', '')} – {end}",
            job_meta_style,
        ))
        desc = exp.get("description", "")
        for line in desc.split(". "):
            line = line.strip()
            if line:
                elements.append(Paragraph(f"• {line}.", bullet_style))
        if exp.get("technologies"):
            tech_str = ", ".join(exp["technologies"])
            elements.append(Paragraph(f"<i>Technologies: {tech_str}</i>", job_meta_style))

    # ── Education ──
    elements.append(Paragraph("EDUCATION", section_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT))

    for edu in educations:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            f"<b>{edu['degree']} in {edu.get('field_of_study', '')}</b> — {edu['institution']}",
            job_title_style,
        ))
        meta = f"{edu.get('start_year', '')} – {edu.get('end_year', '')}"
        if edu.get("gpa"):
            meta += f" &nbsp;|&nbsp; GPA: {edu['gpa']}"
        elements.append(Paragraph(meta, job_meta_style))

    # ── Skills ──
    elements.append(Paragraph("SKILLS", section_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT))
    elements.append(Spacer(1, 4))

    # Group by category
    categories: dict[str, list[str]] = {}
    for s in skills:
        cat = (s.get("category") or "other").title()
        categories.setdefault(cat, []).append(s["name"])

    for cat, skill_names in categories.items():
        elements.append(Paragraph(f"<b>{cat}:</b> {', '.join(skill_names)}", body_style))

    doc.build(elements)
    return str(output_path)


if __name__ == "__main__":
    # Quick test
    from scripts.seed_demo import (
        DEMO_CANDIDATE, DEMO_WORK_EXPERIENCES, DEMO_EDUCATIONS, DEMO_SKILLS
    )
    path = generate_demo_resume("test-id", DEMO_CANDIDATE, DEMO_WORK_EXPERIENCES, DEMO_EDUCATIONS, DEMO_SKILLS)
    print(f"Resume generated: {path}")
