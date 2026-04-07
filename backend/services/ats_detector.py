"""
Two-step detection:
1. URL pattern matching (fast, no browser needed)
2. DOM fingerprinting (fallback — loads page and inspects DOM)
No hardcoded per-URL logic — detection generalises to new job URLs.
"""
import re
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from backend.db.models import ATSPlatform


# URL Pattern Rules

ATS_URL_PATTERNS: list[tuple[re.Pattern, ATSPlatform]] = [
    # Workday — myworkdayjobs.com or workday.com
    (re.compile(r"myworkdayjobs\.com|workday\.com/.*jobs", re.I), ATSPlatform.WORKDAY),
    # Greenhouse
    (re.compile(r"greenhouse\.io|boards\.greenhouse\.io", re.I), ATSPlatform.GREENHOUSE),
    # Lever
    (re.compile(r"lever\.co|jobs\.lever\.co", re.I), ATSPlatform.LEVER),
    # LinkedIn
    (re.compile(r"linkedin\.com/jobs", re.I), ATSPlatform.LINKEDIN),
    # iCIMS
    (re.compile(r"icims\.com|careers\.icims\.com", re.I), ATSPlatform.ICIMS),
]


# DOM Fingerprints

ATS_DOM_FINGERPRINTS: list[tuple[list[str], ATSPlatform]] = [
    # Workday — unique data-automation-id attributes
    (
        ["[data-automation-id='jobPostingHeader']", "wd-popup-content", "WDAY"],
        ATSPlatform.WORKDAY,
    ),
    # Greenhouse — gh-header or application form IDs
    (
        ["#application_form", ".greenhouse-job-board", "data-gh-atssourcecode"],
        ATSPlatform.GREENHOUSE,
    ),
    # Lever — lever-job-listing, lever-apply
    (
        ["[data-lever-source]", ".lever-job-listing", "#lever-apply"],
        ATSPlatform.LEVER,
    ),
    # LinkedIn
    (
        [".jobs-apply-button", ".job-apply-button--top-card", "linkedin-icon"],
        ATSPlatform.LINKEDIN,
    ),
    # iCIMS
    (
        ["iCIMS_Resumator", "icims-NavBar", "#iCIMS_Content"],
        ATSPlatform.ICIMS,
    ),
]


@dataclass
class ATSDetectionResult:
    platform: ATSPlatform
    confidence: str  # "url_pattern" | "dom_fingerprint" | "unknown"
    details: Optional[str] = None


class ATSDetector:
    """Detects which ATS platform a job URL belongs to."""

    def detect_from_url(self, url: str) -> ATSDetectionResult:
        """Step 1: Fast detection from URL pattern."""
        for pattern, platform in ATS_URL_PATTERNS:
            if pattern.search(url):
                logger.info(f"ATS detected from URL: {platform.value} for {url}")
                return ATSDetectionResult(
                    platform=platform,
                    confidence="url_pattern",
                    details=f"Matched pattern: {pattern.pattern}",
                )
        return ATSDetectionResult(platform=ATSPlatform.UNKNOWN, confidence="url_pattern")

    async def detect_from_dom(self, page: Page, url: str) -> ATSDetectionResult:
        """Step 2: DOM fingerprint detection after page load."""
        logger.info(f"Attempting DOM fingerprint detection for {url}")

        page_source = await page.content()

        for selectors, platform in ATS_DOM_FINGERPRINTS:
            for selector in selectors:
                # Check both as CSS selector and as substring in source
                try:
                    el = await page.query_selector(selector)
                    if el:
                        logger.info(f"ATS detected from DOM selector '{selector}': {platform.value}")
                        return ATSDetectionResult(
                            platform=platform,
                            confidence="dom_fingerprint",
                            details=f"Matched selector: {selector}",
                        )
                except Exception:
                    pass

                if selector in page_source:
                    logger.info(f"ATS detected from DOM source '{selector}': {platform.value}")
                    return ATSDetectionResult(
                        platform=platform,
                        confidence="dom_fingerprint",
                        details=f"Matched in page source: {selector}",
                    )

        return ATSDetectionResult(
            platform=ATSPlatform.UNKNOWN,
            confidence="dom_fingerprint",
            details="No fingerprint matched",
        )

    async def detect(self, url: str, page: Optional[Page] = None) -> ATSDetectionResult:
        """Main entry: URL pattern first, then DOM if needed."""
        result = self.detect_from_url(url)
        if result.platform != ATSPlatform.UNKNOWN:
            return result

        if page is not None:
            result = await self.detect_from_dom(page, url)

        if result.platform == ATSPlatform.UNKNOWN:
            logger.warning(f"Could not detect ATS for {url}")

        return result


ats_detector = ATSDetector()
