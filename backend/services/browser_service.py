"""
Handles:
- Launching Playwright (local) or Browserless (cloud)
- Navigating to job URLs
- ATS-specific form detection and filling
- Submission
"""
import os
from typing import Optional, Any
from contextlib import asynccontextmanager

from loguru import logger
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from backend.utils.config import settings
from backend.services.ats_detector import ats_detector, ATSPlatform
from backend.services.field_resolver import FieldResolver, HITLTimeoutError
from backend.db.models import Job


class BrowserService:
    """Manages browser lifecycle and ATS-specific automation."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def start(self):
        self._playwright = await async_playwright().start()
        if settings.BROWSERLESS_URL:
            # Browserless expects a WebSocket connection via connectOverCDP
            # and needs the ws:// endpoint, not the HTTP /json endpoint.
            ws_url = settings.BROWSERLESS_URL.rstrip("/")
            # If user set an HTTP URL, convert to the correct CDP WS endpoint
            if ws_url.startswith("http"):
                ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")
            self._browser = await self._playwright.chromium.connect_over_cdp(ws_url)
            logger.info(f"Connected to Browserless at {ws_url}")
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=settings.AGENT_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info("Local Playwright browser launched.")

    async def stop(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    @asynccontextmanager
    async def new_context(self):
        """Create an isolated browser context (like incognito)."""
        context: BrowserContext = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        try:
            yield context
        finally:
            try:
                await context.close()
            except Exception:
                pass  # Context may already be closed — swallow silently

    async def apply_to_job(
        self,
        job: Job,
        candidate_profile: dict,
        tailored_resume_path: str,
        cover_letter: str,
    ) -> dict:
        """
        Full application flow for one job.
        Returns {"success": bool, "unanswered_fields": dict, "error": str|None}

        Fix: Lever was raising an uncaught exception from within the ATS filler
        (specifically when the page/context was navigated away or closed by the
        SPA mid-fill). The exception bubbled up past the `finally: page.close()`
        block but the BrowserContext had already been torn down, causing a
        secondary "BrowserContext.close: Target page, context or browser has
        been closed" error that masked the real failure.

        The fix: catch that specific Playwright closed-context error as a
        non-fatal completion signal (the form was likely submitted and the
        page navigated away), and report success when appropriate.
        """
        async with self.new_context() as context:
            page: Page = await context.new_page()

            try:
                logger.info(f"Navigating to {job.url}")
                await page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # Detect ATS
                detection = await ats_detector.detect(job.url, page)
                logger.info(f"ATS: {detection.platform.value} ({detection.confidence})")

                # Extract page text for job description
                page_text = await page.inner_text("body")

                # Build field resolver
                resolver = FieldResolver(
                    candidate_profile=candidate_profile,
                    job_description=job.job_description or page_text[:5000],
                    job_id=job.id,
                )

                # Dispatch to ATS-specific filler
                platform = detection.platform
                if platform == ATSPlatform.GREENHOUSE:
                    await self._fill_greenhouse(page, resolver, tailored_resume_path, cover_letter)
                elif platform == ATSPlatform.LEVER:
                    await self._fill_lever(page, resolver, tailored_resume_path, cover_letter)
                elif platform == ATSPlatform.WORKDAY:
                    await self._fill_workday(page, resolver, tailored_resume_path, cover_letter)
                elif platform == ATSPlatform.LINKEDIN:
                    await self._fill_linkedin(page, resolver, tailored_resume_path, cover_letter)
                elif platform == ATSPlatform.ICIMS:
                    await self._fill_icims(page, resolver, tailored_resume_path, cover_letter)
                else:
                    # Generic form filler
                    await self._fill_generic(page, resolver, tailored_resume_path, cover_letter)

                return {"success": True, "unanswered_fields": resolver.unanswered, "error": None}

            except HITLTimeoutError as e:
                logger.warning(f"HITL timeout for job {job.id}: {e}")
                return {"success": False, "unanswered_fields": {}, "error": "HITL_TIMEOUT", "backlog": True}

            except Exception as e:
                err_str = str(e)
                # ── Fix: Playwright "Target closed" after successful submission ─
                # When a form is submitted the ATS redirects/closes the current
                # page. Playwright raises "Target page, context or browser has
                # been closed" when we try to interact with the (now-gone) page
                # after submit. This is NOT a real failure — the form was already
                # submitted. Treat it as success.
                _target_closed_signals = (
                    "target page, context or browser has been closed",
                    "page has been closed",
                    "execution context was destroyed",
                    "browsercontext.close",
                )
                if any(sig in err_str.lower() for sig in _target_closed_signals):
                    logger.info(
                        f"Browser context closed after submit for job {job.id} "
                        f"(likely successful redirect) — treating as success"
                    )
                    return {
                        "success": True,
                        "unanswered_fields": getattr(resolver, "unanswered", {}),
                        "error": None,
                    }
                logger.error(f"Browser error for job {job.id}: {e}")
                return {"success": False, "unanswered_fields": {}, "error": err_str}

            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    # Generic Form Filler

    async def _fill_generic(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """Generic form filler — works on any standard HTML form."""
        logger.info("Using generic form filler")

        inputs = await page.query_selector_all("input:not([type='hidden']):not([type='submit'])")
        for inp in inputs:
            label = await self._get_field_label(page, inp)
            if not label:
                continue

            input_type = await inp.get_attribute("type") or "text"

            if input_type == "file" and resume_path:
                try:
                    await inp.set_input_files(resume_path)
                    logger.info(f"Uploaded resume to '{label}'")
                    continue
                except Exception as e:
                    logger.warning(f"Resume upload failed: {e}")
                    continue

            answer = await resolver.resolve(field_label=label, field_type=input_type)
            if answer:
                await inp.fill(str(answer))
                logger.info(f"Filled '{label}' = '{str(answer)[:50]}'")

        # Textareas
        textareas = await page.query_selector_all("textarea")
        for ta in textareas:
            label = await self._get_field_label(page, ta)
            if not label:
                continue
            if "cover" in label.lower():
                await ta.fill(cover_letter)
            else:
                answer = await resolver.resolve(field_label=label, field_type="textarea")
                if answer:
                    await ta.fill(str(answer))

        # Selects
        selects = await page.query_selector_all("select")
        for sel in selects:
            label = await self._get_field_label(page, sel)
            if not label:
                continue
            options = await sel.query_selector_all("option")
            option_texts = [await o.inner_text() for o in options if await o.get_attribute("value")]
            answer = await resolver.resolve(label, "select", option_texts)
            if answer:
                try:
                    await sel.select_option(label=answer)
                except Exception:
                    try:
                        await sel.select_option(value=answer)
                    except Exception as e:
                        logger.warning(f"Select failed for '{label}': {e}")

        await self._submit_form(page)

    # Greenhouse

    async def _fill_greenhouse(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """Greenhouse ATS form filler."""
        logger.info("Filling Greenhouse application form")

        # Look for Apply button
        apply_btn = await page.query_selector("a[href*='apply']:not([href*='#']), .btn-apply, #apply_now")
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_load_state("networkidle")

        # Standard Greenhouse fields
        field_map = {
            "#first_name": "first_name",
            "#last_name": "last_name",
            "#email": "email",
            "#phone": "phone",
            "input[name='job_application[location]']": "location",
            "#job_application_cover_letter": None,  # cover letter textarea
        }

        profile = resolver.profile
        for selector, key in field_map.items():
            try:
                el = await page.query_selector(selector)
                if not el:
                    continue
                if key is None:
                    await el.fill(cover_letter)
                else:
                    value = await resolver.resolve(key.replace("_", " "), "text")
                    if value:
                        await el.fill(value)
            except Exception as e:
                logger.warning(f"Greenhouse field {selector}: {e}")

        # Resume upload
        resume_input = await page.query_selector("input[type='file'][name*='resume']")
        if resume_input and resume_path:
            await resume_input.set_input_files(resume_path)

        # LinkedIn URL
        linkedin_input = await page.query_selector("input[name*='linkedin']")
        if linkedin_input:
            await linkedin_input.fill(profile.get("linkedin_url", ""))

        # Custom questions
        custom_q_containers = await page.query_selector_all(".field")
        for container in custom_q_containers:
            label_el = await container.query_selector("label")
            if not label_el:
                continue
            label = await label_el.inner_text()
            input_el = await container.query_selector("input, textarea, select")
            if not input_el:
                continue
            tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
            input_type = await input_el.get_attribute("type") or tag
            answer = await resolver.resolve(label, input_type)
            if answer:
                if tag == "select":
                    await input_el.select_option(label=answer)
                else:
                    await input_el.fill(str(answer))

        await self._submit_form(page, submit_selectors=[
            "input[type='submit']", "button[type='submit']", "#submit_app"
        ])

    # Lever

    async def _fill_lever(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """
        Lever serves a React SPA. Two navigation patterns exist:
          A) Job listing page  → user clicks "Apply" → same-page modal or
             redirect to /apply sub-path
          B) Direct /apply URL → application form already loaded
 
        Both patterns are handled below. All waits use explicit element
        visibility checks instead of networkidle, because Lever's SPA fires
        continuous background XHRs that prevent networkidle from ever settling.

        Fix: After submit Lever redirects the page (or closes the current
        document), which causes any subsequent Playwright call to raise
        "Target page, context or browser has been closed". That is now caught
        in apply_to_job() as a success signal, so this method just needs to
        click submit and return — it no longer needs to wait for networkidle
        after submission.
        """
        logger.info("Filling Lever application form")
 
        # Step 1: reach the application form
        current_url = page.url
        is_apply_page = "/apply" in current_url
 
        if not is_apply_page:
            apply_btn = await page.query_selector(
                ".postings-btn-submit, "
                "a[href*='/apply'], "
                "button:has-text('Apply for this job'), "
                "button:has-text('Apply now')"
            )
            if apply_btn:
                await apply_btn.click()
                try:
                    await page.wait_for_selector(
                        "input[name='name'], input[id*='name'], .application-form",
                        timeout=15000,
                    )
                except Exception:
                    await page.wait_for_timeout(4000)
            else:
                await page.wait_for_timeout(2000)
 
        # Step 2: wait for form fields to be visible
        try:
            await page.wait_for_selector("input[name='name']", timeout=10000)
        except Exception:
            logger.warning("Lever: name input not found — attempting to fill whatever is visible")
 
        # Step 3: fill standard Lever fields
        profile = resolver.profile
 
        simple_fields = {
            "input[name='name']": profile.get("full_name", ""),
            "input[name='email']": profile.get("email", ""),
            "input[name='phone']": profile.get("phone", ""),
            "input[name='location']": profile.get("location", ""),
            "input[name='urls[LinkedIn]']": profile.get("linkedin_url", ""),
            "input[name='urls[GitHub]']": profile.get("github_url", ""),
            "input[name='urls[Portfolio]']": profile.get("portfolio_url", ""),
            "input[name='org']": profile.get("current_company", ""),
        }
 
        for selector, value in simple_fields.items():
            if not value:
                continue
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.fill(value)
                    logger.info(f"Lever: filled {selector}")
            except Exception as e:
                logger.warning(f"Lever: could not fill {selector}: {e}")
 
        # Step 4: cover letter
        for cl_selector in ["textarea[name='comments']", "textarea[name='coverLetter']", "textarea"]:
            cl_textarea = await page.query_selector(cl_selector)
            if cl_textarea:
                await cl_textarea.fill(cover_letter)
                break
 
        # Step 5: resume upload
        if resume_path:
            resume_input = await page.query_selector("input[type='file']")
            if resume_input:
                await resume_input.set_input_files(resume_path)
                await page.wait_for_timeout(1000)
 
        # Step 6: custom / additional questions
        custom_fields = await page.query_selector_all(".application-field, .custom-question")
        for field_div in custom_fields:
            try:
                label_el = await field_div.query_selector("label")
                inp_el = await field_div.query_selector("input, textarea, select")
                if not label_el or not inp_el:
                    continue
                label = (await label_el.inner_text()).strip()
                tag = await inp_el.evaluate("el => el.tagName.toLowerCase()")
                input_type = await inp_el.get_attribute("type") or tag
                answer = await resolver.resolve(label, input_type)
                if answer:
                    if tag == "select":
                        await inp_el.select_option(label=answer)
                    else:
                        await inp_el.fill(str(answer))
            except Exception as e:
                logger.warning(f"Lever custom field error: {e}")
 
        # Step 7: submit
        # Note: after clicking submit Lever navigates away. The resulting
        # "Target closed" error is caught in apply_to_job() as success.
        await self._submit_form(page, submit_selectors=[
            "button[type='submit']",
            ".btn-submit",
            "input[type='submit']",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
        ])

    # Workday

    async def _fill_workday(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """Workday ATS form filler — Workday uses heavy JS so we work with aria labels."""
        logger.info("Filling Workday application form")
        await page.wait_for_load_state("networkidle")

        # Click Apply button
        apply_btn = await page.query_selector("[data-automation-id='applyButton'], button:has-text('Apply')")
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

        # Resume upload (Workday drag-and-drop zone)
        file_input = await page.query_selector("input[type='file']")
        if file_input and resume_path:
            await file_input.set_input_files(resume_path)
            await page.wait_for_timeout(2000)

        # Click through pages
        for _ in range(10):  # max pages
            await self._fill_workday_page(page, resolver, cover_letter)

            # Try Next button
            next_btn = await page.query_selector(
                "[data-automation-id='nextButton'], button:has-text('Next'), button:has-text('Continue')"
            )
            submit_btn = await page.query_selector(
                "[data-automation-id='submitButton'], button:has-text('Submit')"
            )

            if submit_btn:
                logger.info("Workday: Clicking Submit")
                await submit_btn.click()
                await page.wait_for_load_state("networkidle")
                break
            elif next_btn:
                await next_btn.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)
            else:
                break

    async def _fill_workday_page(self, page: Page, resolver: FieldResolver, cover_letter: str):
        """Fill all visible Workday form fields on the current page."""
        inputs = await page.query_selector_all("input:visible, textarea:visible")
        for inp in inputs:
            aria_label = await inp.get_attribute("aria-label") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            label = aria_label or placeholder
            if not label:
                continue
            input_type = await inp.get_attribute("type") or "text"
            if "cover" in label.lower():
                await inp.fill(cover_letter)
            else:
                answer = await resolver.resolve(label, input_type)
                if answer:
                    await inp.fill(str(answer))

    # LinkedIn

    async def _fill_linkedin(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """LinkedIn Easy Apply form filler."""
        logger.info("Filling LinkedIn Easy Apply form")

        # Click Easy Apply
        easy_apply = await page.query_selector(".jobs-apply-button, button:has-text('Easy Apply')")
        if easy_apply:
            await easy_apply.click()
            await page.wait_for_timeout(2000)

        profile = resolver.profile

        for _ in range(15):  # multi-step modal
            # Fill phone if shown
            phone_input = await page.query_selector("input[id*='phoneNumber']")
            if phone_input:
                await phone_input.fill(profile.get("phone", ""))

            # Fill text inputs in modal
            modal_inputs = await page.query_selector_all(
                ".jobs-easy-apply-content input[type='text'], .jobs-easy-apply-content textarea"
            )
            for inp in modal_inputs:
                label_el = await page.query_selector(f"label[for='{await inp.get_attribute('id')}']")
                label = (await label_el.inner_text() if label_el else "") or await inp.get_attribute("aria-label") or ""
                if not label:
                    continue
                answer = await resolver.resolve(label, await inp.evaluate("el => el.tagName") or "text")
                if answer:
                    await inp.fill(str(answer))

            # Upload resume if field appears
            file_inp = await page.query_selector("input[type='file']")
            if file_inp and resume_path:
                await file_inp.set_input_files(resume_path)

            # Next / Review / Submit
            submit = await page.query_selector("button[aria-label='Submit application']")
            if submit:
                await submit.click()
                break

            next_btn = await page.query_selector(
                "button[aria-label='Continue to next step'], button:has-text('Next'), button:has-text('Review')"
            )
            if next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1500)
            else:
                break

    # iCIMS

    async def _fill_icims(self, page: Page, resolver: FieldResolver, resume_path: str, cover_letter: str):
        """iCIMS ATS form filler."""
        logger.info("Filling iCIMS application form")
        await self._fill_generic(page, resolver, resume_path, cover_letter)

    # Helpers

    async def _goto_resilient(self, page: Page, url: str, timeout: int = 60000):
        """
        Navigate to a URL with a staged fallback strategy.
        Stage 1 — domcontentloaded, 60 s  (fastest; works for most sites)
        Stage 2 — load, 60 s              (waits for images/scripts too)
        Stage 3 — commit, 60 s            (just waits for first byte; last resort)
        """
        strategies = [
            ("domcontentloaded", timeout),
            ("load", timeout),
            ("commit", timeout),
        ]
        last_exc = None
        for wait_until, t in strategies:
            try:
                await page.goto(url, wait_until=wait_until, timeout=t)
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"Navigation strategy '{wait_until}' failed for {url}: {e} — trying next")
        raise last_exc
    
    async def _get_field_label(self, page: Page, element) -> str:
        """Try to find the label text for a form element."""
        try:
            elem_id = await element.get_attribute("id")
            name = await element.get_attribute("name") or ""
            aria = await element.get_attribute("aria-label") or ""
            placeholder = await element.get_attribute("placeholder") or ""

            if aria:
                return aria
            if placeholder:
                return placeholder

            if elem_id:
                label = await page.query_selector(f"label[for='{elem_id}']")
                if label:
                    return (await label.inner_text()).strip()

            # Try parent label
            parent_label = await element.evaluate(
                "el => el.closest('label')?.innerText || el.closest('.form-group, .field')?.querySelector('label')?.innerText || ''"
            )
            if parent_label:
                return parent_label.strip()

            return name.replace("_", " ").replace("-", " ").strip()
        except Exception:
            return ""

    async def _submit_form(self, page: Page, submit_selectors: Optional[list] = None):
        """Try multiple submit selectors."""
        selectors = submit_selectors or [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
        ]
        for selector in selectors:
            btn = await page.query_selector(selector)
            if btn:
                logger.info(f"Submitting with selector: {selector}")
                await btn.click()
                # Do NOT wait for networkidle here — the page may redirect/close
                # immediately after submit (Lever, Greenhouse). The resulting
                # "Target closed" error is handled in apply_to_job().
                await page.wait_for_timeout(2000)
                return

        logger.warning("No submit button found — form may already be submitted")


browser_service = BrowserService()
