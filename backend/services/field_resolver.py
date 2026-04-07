"""
Resolves form field values through the precedence chain:
1. Profile DB (personal info, work history, education, skills)
2. Custom Answers (key-value store)
3. LLM Inference (Claude infers from candidate context)
4. HITL Escalation (30s timeout, then backlog)
5. Log & Skip (if nothing works)
"""
import re
from typing import Optional, Any

from loguru import logger

from backend.services.llm_service import llm_service
from backend.utils.hitl_manager import hitl_manager


# Maps common form field labels → candidate profile dict paths

PROFILE_FIELD_MAP = {
    # Personal info
    r"(first.?name|given.?name)": lambda p: p.get("full_name", "").split()[0] if p.get("full_name") else "",
    r"(last.?name|family.?name|surname)": lambda p: " ".join(p.get("full_name", "").split()[1:]) if p.get("full_name") else "",
    r"(full.?name|your.?name|name)": lambda p: p.get("full_name", ""),
    r"(email|e-?mail.?address)": lambda p: p.get("email", ""),
    r"(phone|mobile|telephone|contact.?number)": lambda p: p.get("phone", ""),
    r"(city|location|current.?location|where.?are.?you.?located)": lambda p: p.get("location", ""),
    r"(linkedin|linkedin.?url|linkedin.?profile)": lambda p: p.get("linkedin_url", ""),
    r"(github|github.?url|github.?profile)": lambda p: p.get("github_url", ""),
    r"(portfolio|website|personal.?website)": lambda p: p.get("portfolio_url", ""),
    r"(years.?of.?experience|experience.?years|how.?many.?years)": lambda p: str(p.get("years_of_experience", "")),
    r"(summary|professional.?summary|about.?you|tell.?us.?about.?yourself)": lambda p: p.get("summary", ""),
}


class FieldResolver:
    """Resolves form field values through the precedence chain."""

    def __init__(self, candidate_profile: dict, job_description: str, job_id: str):
        self.profile = candidate_profile
        self.job_description = job_description
        self.job_id = job_id
        self.unanswered: dict = {}

        # Build custom answers lookup (lowercase key → answer)
        self.custom_answers = {
            qa["question_key"].lower().replace(" ", "_"): qa["answer"]
            for qa in candidate_profile.get("custom_answers", [])
        }

    def resolve_from_profile(self, field_label: str) -> Optional[str]:
        """Step 1: Match field label against known profile fields."""
        label_lower = field_label.lower().strip()

        for pattern, extractor in PROFILE_FIELD_MAP.items():
            if re.search(pattern, label_lower):
                value = extractor(self.profile)
                if value:
                    logger.debug(f"[Profile] '{field_label}' → '{value[:50]}'")
                    return value
        return None

    def resolve_from_custom_answers(self, field_label: str) -> Optional[str]:
        """Step 2: Check custom answers key-value store."""
        label_lower = field_label.lower().strip().replace(" ", "_").replace("-", "_")

        # Direct key match
        if label_lower in self.custom_answers:
            answer = self.custom_answers[label_lower]
            logger.debug(f"[CustomAnswers] '{field_label}' → '{answer}' (exact)")
            return answer

        # Fuzzy match — check if any custom answer key is contained in the label
        for key, answer in self.custom_answers.items():
            key_words = set(key.replace("_", " ").split())
            label_words = set(label_lower.replace("_", " ").split())
            # Match if >50% of key words appear in label
            if key_words and len(key_words & label_words) / len(key_words) > 0.5:
                logger.debug(f"[CustomAnswers] '{field_label}' → '{answer}' (fuzzy key='{key}')")
                return answer

        return None

    async def resolve_from_llm(
        self, field_label: str, field_type: str, field_options: Optional[list]
    ) -> tuple[Optional[str], bool]:
        """
        Step 3: LLM inference.
        Returns (answer, should_escalate_to_hitl)
        """
        result = await llm_service.infer_form_field(
            field_label=field_label,
            field_type=field_type,
            field_options=field_options,
            candidate_profile=self.profile,
            job_description=self.job_description,
        )

        answer = result.get("answer", "")
        confidence = result.get("confidence", 0.0)
        should_escalate = result.get("should_escalate", False) or confidence < 0.6

        logger.info(
            f"[LLM] '{field_label}' → '{answer[:50]}' "
            f"(confidence={confidence:.2f}, escalate={should_escalate})"
        )

        if not should_escalate and answer:
            return answer, False
        return answer, True

    async def resolve_from_hitl(
        self, field_label: str, field_type: str, field_options: Optional[list], llm_suggestion: str
    ) -> Optional[str]:
        """
        Step 4: HITL escalation.
        Returns the user's answer, or None on timeout (→ backlog).
        """
        context = (
            f"Field: {field_label}\n"
            f"Type: {field_type}\n"
            f"LLM suggestion: {llm_suggestion or 'N/A'}\n"
            f"Options: {field_options or 'Free text'}"
        )

        answer = await hitl_manager.request_answer(
            job_id=self.job_id,
            field_label=field_label,
            field_type=field_type,
            field_options=field_options,
            context=context,
        )

        return answer  # None = timeout

    async def resolve(
        self,
        field_label: str,
        field_type: str = "text",
        field_options: Optional[list] = None,
        skip_hitl: bool = False,
    ) -> Optional[str]:
        """
        Main resolution method — runs through the full precedence chain.
        Returns the answer string, or None (field will be logged as unanswered).
        Raises HITLTimeoutException if HITL times out (caller should move job to backlog).
        """
        # Step 1: Profile DB
        answer = self.resolve_from_profile(field_label)
        if answer:
            return answer

        # Step 2: Custom Answers
        answer = self.resolve_from_custom_answers(field_label)
        if answer:
            return answer

        # Step 3: LLM Inference
        llm_answer, should_escalate = await self.resolve_from_llm(
            field_label, field_type, field_options
        )

        if not should_escalate and llm_answer:
            return llm_answer

        # Step 4: HITL (unless skipped)
        if not skip_hitl:
            hitl_answer = await self.resolve_from_hitl(
                field_label, field_type, field_options, llm_answer
            )
            if hitl_answer is None:
                # Timeout → caller should handle backlog
                self.unanswered[field_label] = "HITL_TIMEOUT"
                raise HITLTimeoutError(
                    f"HITL timeout on field '{field_label}' for job {self.job_id}"
                )

            # Save to custom answers for future runs (in-memory, caller persists to DB)
            key = field_label.lower().replace(" ", "_")
            self.custom_answers[key] = hitl_answer
            logger.info(f"[HITL] Saved new custom answer: {key} = {hitl_answer}")
            return hitl_answer

        # Step 5: Log as unanswered
        self.unanswered[field_label] = llm_answer or "UNANSWERED"
        return llm_answer or None


class HITLTimeoutError(Exception):
    """Raised when HITL times out — job should move to backlog."""
    pass
