import json
import os
import platform
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from html import unescape
from html.parser import HTMLParser
from math import isfinite
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.authorization import require_dice_automation_authorized
from core.browser_detector import get_browser_path
from core.resumes import JobPosting, ResumeService
from core.resumes.models import ResumeTailoringError


# Load environment variables
load_dotenv()


def get_web_driver(headless=False, retry_with_alternative=True):
    """
    Initializes a Selenium WebDriver with fallback options.
    If the primary browser (Brave) fails to load, it will try Chrome as a fallback.

    Parameters:
        headless (bool): Whether to use headless mode
        retry_with_alternative (bool): Whether to try alternative browsers if primary fails

    Returns:
        WebDriver: Initialized WebDriver instance
    """
    # Get browser path from .env or detect it
    web_browser_path = get_browser_path()

    if not web_browser_path:
        raise Exception("Browser path not found in .env file. Please set WEB_BROWSER_PATH.")

    tried_browsers = []
    tried_browser_paths = set()

    # Try the primary browser first
    try:
        options = Options()
        options.binary_location = web_browser_path

        # Add headless mode options if requested
        if headless:
            options.add_argument("--headless=new")

        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-features=EnableEphemeralFlashPermission")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")

        # Clear browser cache and cookies
        options.add_argument("--disable-application-cache")
        options.add_argument("--incognito")

        driver = webdriver.Chrome(options=options)

        # Test local navigation without making an unrelated external request.
        driver.get("data:text/html,<body>ready</body>")
        driver.find_element(By.TAG_NAME, "body")  # Should work if page loaded

        print(f"Successfully initialized browser: {os.path.basename(web_browser_path)}")
        return driver

    except Exception as e:
        tried_browsers.append(os.path.basename(web_browser_path))
        tried_browser_paths.add(os.path.realpath(web_browser_path))
        print(f"Error initializing primary browser ({os.path.basename(web_browser_path)}): {e}")

        if not retry_with_alternative:
            raise Exception(f"Failed to initialize browser and retry is disabled.")

    # If we get here, the primary browser failed - let's try alternatives
    system = platform.system()
    alternative_paths = []

    if system == "Darwin":  # macOS
        alternative_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif system == "Windows":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        alternative_paths = [
            f"{program_files}\\Google\\Chrome\\Application\\chrome.exe",
            f"{program_files_x86}\\Google\\Chrome\\Application\\chrome.exe",
            f"{program_files}\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            f"{program_files_x86}\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            f"{program_files}\\Microsoft\\Edge\\Application\\msedge.exe",
            f"{program_files_x86}\\Microsoft\\Edge\\Application\\msedge.exe",
        ]
    else:  # Linux
        alternative_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/brave-browser",
            "/usr/bin/microsoft-edge",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]

    # Try each alternative browser
    for alt_path in alternative_paths:
        normalized_path = os.path.realpath(alt_path)
        if normalized_path not in tried_browser_paths and os.path.exists(alt_path):
            try:
                options = Options()
                options.binary_location = alt_path

                if headless:
                    options.add_argument("--headless=new")

                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")
                options.add_argument("--incognito")  # Use incognito to avoid cache issues

                driver = webdriver.Chrome(options=options)

                # Test local navigation without making an unrelated external request.
                driver.get("data:text/html,<body>ready</body>")
                driver.find_element(By.TAG_NAME, "body")

                print(f"Successfully initialized alternative browser: {os.path.basename(alt_path)}")

                # Update the .env file with working browser
                from dotenv import set_key, find_dotenv

                dotenv_path = find_dotenv()
                if dotenv_path:
                    set_key(dotenv_path, "WEB_BROWSER_PATH", alt_path)
                    print(f"Updated WEB_BROWSER_PATH in .env file to: {alt_path}")

                return driver

            except Exception as e:
                tried_browsers.append(os.path.basename(alt_path))
                tried_browser_paths.add(normalized_path)
                print(f"Error initializing alternative browser ({os.path.basename(alt_path)}): {e}")

    # If we get here, all browsers failed
    raise Exception(f"Failed to initialize any browser. Tried: {', '.join(tried_browsers)}")


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    PREVIEW_READY = "preview_ready"
    UPLOAD_VERIFIED = "upload_verified"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunMode(StrEnum):
    """Allowed browser side-effect levels for one job."""

    PREVIEW = "preview"
    VERIFY_UPLOAD = "verify_upload"
    SUBMIT = "submit"


class ApplicationProgressStage(StrEnum):
    """Secret-free milestones surfaced by the desktop UI for one job."""

    OPENING_JOB = "opening_job"
    EVALUATING_RESUME = "evaluating_resume"
    CHECKING_EASY_APPLY = "checking_easy_apply"
    PREPARING_RESUME = "preparing_resume"
    RESUME_READY = "resume_ready"
    OPENING_WIZARD = "opening_wizard"
    VERIFYING_UPLOAD = "verifying_upload"
    RESUME_SELECTED = "resume_selected"
    ADVANCING_WIZARD = "advancing_wizard"
    SUBMITTING = "submitting"
    SUBMISSION_CONFIRMED = "submission_confirmed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ApplicationProgress:
    """Bounded UI event that never contains credentials, descriptions, or full paths."""

    stage: ApplicationProgressStage
    message: str
    job_title: str = ""
    status: str = ""
    resume_profile: str = ""
    resume_filename: str = ""
    resume_kind: str = ""


@dataclass(frozen=True)
class ApplicationResult:
    status: ApplicationStatus
    reason: str
    resume_profile: str = ""
    match_score: float | None = None
    resume_filename: str = ""
    resume_selection_attempted: bool = False


_OBSERVABILITY_SECRET = re.compile(
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b",
    re.IGNORECASE,
)
_OBSERVABILITY_LOCAL_PATH = re.compile(
    r"(?<!:)/(?:Users|home|tmp|private|var)/[^,;\n]+|[A-Za-z]:\\[^,;\n]+"
)


def _compact_observability_text(value: Any, *, max_chars: int = 180) -> str:
    """Collapse untrusted UI text and keep events bounded for logs and labels."""

    compact = " ".join(str(value or "").split())
    compact = _OBSERVABILITY_SECRET.sub("[redacted token]", compact)
    compact = _OBSERVABILITY_LOCAL_PATH.sub("[local path]", compact)
    return compact if len(compact) <= max_chars else f"{compact[: max_chars - 1]}…"


def _safe_resume_filename(value: Any) -> str:
    return _compact_observability_text(str(value or "").replace("\\", "/").rsplit("/", 1)[-1])


def _emit_application_progress(
    callback: Callable[[ApplicationProgress], None] | None,
    stage: ApplicationProgressStage,
    message: str,
    *,
    job_title: str,
    status: str = "",
    resume_profile: str = "",
    resume_filename: str = "",
    resume_kind: str = "",
) -> None:
    if callback is None:
        return
    event = ApplicationProgress(
        stage=stage,
        message=_compact_observability_text(message),
        job_title=_compact_observability_text(job_title, max_chars=120),
        status=_compact_observability_text(status, max_chars=40),
        resume_profile=_compact_observability_text(resume_profile, max_chars=40),
        resume_filename=_safe_resume_filename(resume_filename),
        resume_kind=_compact_observability_text(resume_kind, max_chars=20),
    )
    with suppress(Exception):
        callback(event)


@dataclass(frozen=True)
class JobSelection:
    """Result of the read-only, full-description candidate ranking pass."""

    selected_jobs: tuple[dict[str, Any], ...]
    deferred_jobs: tuple[dict[str, Any], ...]
    rejected_jobs: tuple[dict[str, Any], ...]
    assessed_count: int
    cancelled: bool = False


CANDIDATE_POOL_MULTIPLIER = 4


def _visible(elements):
    return next((element for element in elements if element.is_displayed()), None)


def _visible_enabled(elements):
    return next(
        (element for element in elements if element.is_displayed() and element.is_enabled()),
        None,
    )


class _JobDescriptionHTMLParser(HTMLParser):
    """Turn Dice's structured-data HTML description into readable plain text."""

    _BLOCK_TAGS = {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and normalized_tag in self._BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif not self._ignored_depth and normalized_tag in self._BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.fragments.append(data)


def _normalize_description_text(value: str) -> str:
    return "\n".join(
        normalized
        for line in unescape(value).splitlines()
        if (normalized := " ".join(line.split()))
    )


def _plain_text_description(value: str) -> str:
    parser = _JobDescriptionHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    return _normalize_description_text("".join(parser.fragments))


def _same_dice_job_detail_page(first_url: str, second_url: Any) -> bool:
    """Return whether two URLs identify the same exact HTTPS Dice job-detail path."""

    if not isinstance(second_url, str):
        return False
    if not _is_dice_url(first_url, job_detail=True) or not _is_dice_url(
        second_url, job_detail=True
    ):
        return False
    try:
        first_path = urlparse(first_url).path.rstrip("/")
        second_path = urlparse(second_url).path.rstrip("/")
    except ValueError:
        return False
    return bool(first_path) and first_path == second_path


def _extract_structured_job_description(driver) -> str:
    """Read the canonical JobPosting description when Dice changes presentation CSS."""

    try:
        page_url = str(driver.current_url or "")
    except Exception:
        return ""
    selectors = (
        'script[data-testid="jobDetailStructuredData"]',
        'script[type="application/ld+json"]',
    )
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                raw = (
                    element.get_attribute("textContent")
                    or element.get_attribute("innerHTML")
                    or element.text
                    or ""
                )
            except Exception:
                continue
            # Refuse unexpectedly large page-controlled payloads instead of feeding them to
            # the JSON or resume pipeline. Ordinary Dice JobPosting data is far smaller.
            if not 2 <= len(raw) <= 1_000_000:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue

            documents: list[dict[str, Any]] = []
            candidates = payload if isinstance(payload, list) else (payload,)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                documents.append(candidate)
                graph = candidate.get("@graph")
                if isinstance(graph, list):
                    documents.extend(item for item in graph if isinstance(item, dict))
            for document in documents:
                schema_type = document.get("@type")
                schema_types = schema_type if isinstance(schema_type, list) else (schema_type,)
                if "JobPosting" not in schema_types:
                    continue
                if not _same_dice_job_detail_page(page_url, document.get("url")):
                    continue
                description = document.get("description")
                if not isinstance(description, str) or len(description) > 250_000:
                    continue
                text = _plain_text_description(description)
                if 100 <= len(text) <= 200_000:
                    return text
    return ""


def _extract_job_description(driver) -> str:
    selectors = (
        '[data-testid="job-description"]',
        '[data-testid="jobDescription"]',
        "#jobDescription",
        ".job-description",
        # Dice's current Next.js job page uses a content-hashed CSS module prefix,
        # for example ``job-detail-description-module__...__jobDescription``.
        '[class*="job-detail-description-module"][class*="jobDescription"]',
    )
    deadline = time.time() + 12
    while time.time() < deadline:
        for selector in selectors:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                text = _normalize_description_text(element.text or "")
                if len(text) >= 100:
                    return text
        structured_description = _extract_structured_job_description(driver)
        if structured_description:
            return structured_description
        time.sleep(0.4)
    return ""


def _dice_job_identifier(url: str) -> str:
    if not _is_dice_url(url, job_detail=True):
        return ""
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) != 2 or parts[0] != "job-detail":
        return ""
    return parts[1]


def _is_expected_dice_application_url(candidate_url: str, job_url: str) -> bool:
    if not _is_dice_url(candidate_url):
        return False
    job_identifier = _dice_job_identifier(job_url)
    if not job_identifier:
        return False
    parts = [part for part in urlparse(candidate_url).path.split("/") if part]
    return (
        len(parts) == 3
        and parts[0] == "job-applications"
        and parts[1] == job_identifier
        and parts[2] in {"start-apply", "wizard"}
    )


def _is_expected_dice_apply_target(candidate_url: str, job_url: str) -> bool:
    """Accept a direct wizard URL or Dice's login wrapper for that exact wizard."""

    if _is_expected_dice_application_url(candidate_url, job_url):
        return True
    if not _is_dice_url(candidate_url):
        return False
    parsed = urlparse(candidate_url)
    if parsed.path.rstrip("/") != "/dashboard/login":
        return False
    redirect_values = parse_qs(parsed.query).get("redirectUrl", [])
    if len(redirect_values) != 1:
        return False
    redirect_path = redirect_values[0]
    if not redirect_path.startswith("/") or redirect_path.startswith("//"):
        return False
    return _is_expected_dice_application_url(
        f"https://www.dice.com{redirect_path}", job_url
    )


def _is_expected_apply_context(current_url: str, job_url: str) -> bool:
    return _same_dice_job_detail_page(current_url, job_url) or (
        _is_expected_dice_application_url(current_url, job_url)
    )


def _find_apply_control(driver, job_url: str):
    controls = driver.find_elements(
        By.CSS_SELECTOR,
        'button[data-testid="apply-button"], a[data-testid="apply-button"]',
    )
    visible = [control for control in controls if control.is_displayed()]
    already_applied = next(
        (
            control
            for control in visible
            if "applied" in (control.text or "").strip().lower()
            or "application submitted" in (control.text or "").strip().lower()
        ),
        None,
    )
    if already_applied is not None:
        return already_applied
    easy_apply = next(
        (
            control
            for control in visible
            if (
                not (control.get_attribute("href") or "").strip()
                and "easy apply" in (control.text or "").strip().lower()
            )
            or _is_expected_dice_apply_target(
                (control.get_attribute("href") or "").strip(), job_url
            )
        ),
        None,
    )
    return easy_apply or _visible(visible)


def _browser_filename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


_RESUME_INPUT_TERM = re.compile(r"\b(?:resume|curriculum\s+vitae|cv)\b", re.IGNORECASE)
_NON_RESUME_INPUT_TERM = re.compile(
    r"\b(?:avatar|cover\s*letter|photo|portfolio|profile\s*(?:image|picture))\b",
    re.IGNORECASE,
)


def _file_input_descriptor(driver, file_input) -> str:
    values = []
    for attribute in ("name", "id", "aria-label", "data-testid", "title"):
        try:
            values.append(str(file_input.get_attribute(attribute) or ""))
        except Exception:
            continue
    try:
        dom_context = driver.execute_script(
            "const el = arguments[0]; "
            "const text = node => (node && (node.innerText || node.textContent) || '').slice(0, 2000); "
            "const labels = el.labels ? Array.from(el.labels).map(text) : []; "
            "const related = (el.getAttribute('aria-labelledby') || '').split(/\\s+/) "
            ".map(id => document.getElementById(id)).filter(Boolean).map(text); "
            "const scopes = []; let node = el; "
            "for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) "
            "{ scopes.push(text(node)); } "
            "return [...labels, ...related, ...scopes].join(' ');",
            file_input,
        )
        values.append(str(dom_context or ""))
    except Exception:
        pass
    descriptor = " ".join(values)
    descriptor = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", descriptor)
    descriptor = re.sub(r"[_-]+", " ", descriptor)
    return " ".join(descriptor.split())


def _safe_file_input_attribute(value: object) -> str:
    """Return selector-relevant metadata without exposing file values or page content."""

    compact = re.sub(r"[^a-z0-9._:-]+", "-", str(value or "").casefold()).strip("-")
    return compact[:80] or "none"


def _file_input_signature(file_input, position: int) -> str:
    """Describe only stable, non-content attributes for a failed upload diagnosis."""

    attributes: list[str] = []
    for attribute in ("name", "id", "data-testid", "aria-label", "accept"):
        try:
            value = file_input.get_attribute(attribute)
        except Exception:
            value = ""
        attributes.append(f"{attribute}={_safe_file_input_attribute(value)}")
    return f"input-{position}({'; '.join(attributes)})"


def _upload_resume_if_present(
    driver,
    resume_path: str,
    *,
    pre_upload: Callable[[], None] | None = None,
    selection_callback: Callable[[], None] | None = None,
) -> tuple[bool, bool, str]:
    inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    if not inputs:
        return False, False, "Dice did not expose a file input on the current Easy Apply step."
    resume_inputs = []
    for file_input in inputs:
        descriptor = _file_input_descriptor(driver, file_input)
        if _RESUME_INPUT_TERM.search(descriptor) and not _NON_RESUME_INPUT_TERM.search(descriptor):
            resume_inputs.append(file_input)
    if not resume_inputs:
        signatures = ", ".join(
            _file_input_signature(file_input, position)
            for position, file_input in enumerate(inputs, start=1)
        )
        return (
            True,
            False,
            "Dice showed file input controls, but none could be safely identified as a "
            f"resume/CV field. Field metadata: {signatures}",
        )
    if len(resume_inputs) != 1:
        return (
            True,
            False,
            "Dice showed multiple possible resume/CV upload fields; the app did not choose "
            "one automatically.",
        )
    filename = os.path.basename(resume_path).lower()
    for file_input in resume_inputs:
        try:
            if pre_upload is not None:
                pre_upload()
            if selection_callback is not None:
                selection_callback()
            file_input.send_keys(resume_path)

            def intended_file_selected(current_driver):
                selected_name = current_driver.execute_script(
                    "const files = arguments[0].files; "
                    "return files && files.length ? files[0].name : '';",
                    file_input,
                )
                if _browser_filename(str(selected_name or "")) == filename:
                    return True
                value = file_input.get_attribute("value") or ""
                return _browser_filename(value) == filename

            WebDriverWait(driver, 12, poll_frequency=0.25).until(intended_file_selected)
            if pre_upload is not None:
                pre_upload()
            return True, True, ""
        except ResumeTailoringError:
            raise
        except Exception:
            continue
    return (
        True,
        False,
        "Dice exposed the intended resume field, but it did not accept or report the selected "
        "filename.",
    )


def _confirmation_present(driver):
    selectors = (
        '[data-testid="job-application-success-card"]',
        '[data-testid="application-success"]',
        "header.post-apply-banner h1",
    )
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            if not element.is_displayed():
                continue
            if selector.startswith("[data-testid="):
                return True
            if "application submitted" in (element.text or "").strip().lower():
                return True
    return False


def _has_visible_screening_controls(driver) -> bool:
    selectors = (
        'input:not([type="hidden"]):not([type="file"]):not([type="submit"]):not([type="button"])',
        "select",
        "textarea",
        '[role="checkbox"]',
        '[role="radio"]',
        '[contenteditable="true"]',
    )
    return any(
        element.is_displayed()
        for selector in selectors
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
    )


def _is_dice_url(url: str, *, job_detail: bool = False) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.hostname != "www.dice.com":
        return False
    return not job_detail or parsed.path.startswith("/job-detail/")


def _cancellation_requested(callback: Callable[[], bool] | None) -> bool:
    if callback is None:
        return False
    try:
        return bool(callback())
    except Exception:
        return True


def _decision_metadata(outcome) -> tuple[str, float | None]:
    decision = getattr(outcome, "decision", None)
    if decision is None and hasattr(outcome, "selected_profile"):
        decision = outcome
    if decision is None:
        return "", None
    selected_profile = getattr(decision, "selected_profile", None)
    profile = getattr(selected_profile, "value", str(selected_profile or ""))
    return profile, getattr(decision, "score", None)


def _record_decision_metadata(job: Mapping[str, Any], outcome) -> None:
    if not isinstance(job, dict):
        return
    decision = getattr(outcome, "decision", None)
    if decision is None and hasattr(outcome, "variant_scores"):
        decision = outcome
    if decision is None:
        return
    variant_scores = getattr(decision, "variant_scores", {})
    if isinstance(variant_scores, Mapping):
        for profile, score in variant_scores.items():
            job[f"{str(profile).upper()} Resume Score"] = score
    job["Resume Score Margin"] = getattr(decision, "score_margin", None)
    job["Minimum Winner Margin"] = getattr(decision, "minimum_winner_margin", None)


def _record_resume_metadata(job: Mapping[str, Any], result: ApplicationResult) -> None:
    if not isinstance(job, dict):
        return
    job["Application Status"] = result.status.value
    job["Application Reason"] = result.reason
    if result.resume_profile:
        job["Resume Profile"] = result.resume_profile
    if result.match_score is not None:
        job["Resume Match Score"] = result.match_score
    if result.resume_filename:
        job["Resume Filename"] = result.resume_filename


def build_diverse_candidate_pool(
    job_buckets: list[list[dict[str, Any]]],
    *,
    application_limit: int,
    pool_multiplier: int = CANDIDATE_POOL_MULTIPLIER,
) -> list[dict[str, Any]]:
    """Build a stable, bounded round-robin pool from search-query result buckets."""

    if application_limit < 1:
        raise ValueError("Application limit must be at least 1.")
    if pool_multiplier < 1:
        raise ValueError("Candidate pool multiplier must be at least 1.")

    nonempty_buckets = [bucket for bucket in job_buckets if bucket]
    pool_limit = max(application_limit * pool_multiplier, len(nonempty_buckets))
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    bucket_offsets = [0] * len(nonempty_buckets)

    while len(selected) < pool_limit:
        added_this_round = False
        for bucket_index, bucket in enumerate(nonempty_buckets):
            while bucket_offsets[bucket_index] < len(bucket):
                job = bucket[bucket_offsets[bucket_index]]
                bucket_offsets[bucket_index] += 1
                job_url = str(job.get("Job URL", ""))
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                selected.append(job)
                added_this_round = True
                break
            if len(selected) >= pool_limit:
                break
        if not added_this_round:
            break

    return selected


def candidate_bucket_limits(
    bucket_count: int,
    *,
    application_limit: int,
    pool_multiplier: int = CANDIDATE_POOL_MULTIPLIER,
) -> tuple[int, ...]:
    """Distribute the bounded ranking budget evenly across search queries."""

    if bucket_count < 1:
        return ()
    if application_limit < 1:
        raise ValueError("Application limit must be at least 1.")
    if pool_multiplier < 1:
        raise ValueError("Candidate pool multiplier must be at least 1.")
    pool_limit = max(application_limit * pool_multiplier, bucket_count)
    base_size, extra = divmod(pool_limit, bucket_count)
    return tuple(base_size + (1 if index < extra else 0) for index in range(bucket_count))


def _bounded_page_count(
    total_jobs: int,
    observed_page_size: int,
    *,
    max_pages: int | None,
) -> int:
    page_size = observed_page_size or 20
    page_count = max(1, (total_jobs + page_size - 1) // page_size)
    page_count = min(11, page_count)
    return min(page_count, max_pages) if max_pages is not None else page_count


def rank_eligible_jobs(
    driver,
    jobs: list[dict[str, Any]],
    resume_service: ResumeService,
    *,
    limit: int,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobSelection:
    """Rank resume-eligible Dice jobs by full-description match before applying a cap.

    This preflight pass only navigates to job-detail pages and calls the service's
    side-effect-free ``evaluate`` method. It never inspects or clicks Apply controls and it
    never prepares a tailored resume. Jobs that cannot be assessed confidently are rejected.
    Equal scores retain discovery order for deterministic behavior.
    """

    require_dice_automation_authorized()
    if limit < 1:
        raise ValueError("Job selection limit must be at least 1.")
    evaluator = getattr(resume_service, "evaluate", None)
    if not callable(evaluator):
        raise RuntimeError("Candidate ranking requires a side-effect-free resume evaluator.")

    original_url = driver.current_url
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    assessed_count = 0
    cancelled = False

    def reject(job: dict[str, Any], reason: str) -> None:
        job["Selection Status"] = "ineligible"
        job["Application Status"] = ApplicationStatus.SKIPPED.value
        job["Application Reason"] = reason
        rejected.append(job)

    try:
        total_jobs = len(jobs)
        for discovery_index, job in enumerate(jobs):
            if _cancellation_requested(cancel_requested):
                cancelled = True
                break

            job_title = str(job.get("Job Title", "")).strip()
            if progress_callback is not None:
                progress_callback(discovery_index + 1, total_jobs, job_title or "Unknown")

            job_url = str(job.get("Job URL", ""))
            job_id = str(job.get("Job ID", "")).strip()
            if not _is_dice_url(job_url, job_detail=True):
                reject(job, "Only HTTPS Dice job-detail URLs are accepted for ranking.")
                assessed_count += 1
                continue

            try:
                driver.get(job_url)
                current_url = str(driver.current_url or "")
                if not _same_dice_job_detail_page(job_url, current_url):
                    reject(
                        job,
                        "Dice redirected to a different job detail; skipped to avoid "
                        "matching or applying to the wrong posting.",
                    )
                    assessed_count += 1
                    continue
                description = _extract_job_description(driver)
            except Exception:
                reject(job, "Dice job details could not be opened for safe ranking.")
                assessed_count += 1
                continue
            if not description:
                reject(
                    job,
                    "Dice job description could not be read; skipped to avoid a random application.",
                )
                assessed_count += 1
                continue

            try:
                posting = JobPosting(
                    title=job_title,
                    description=description,
                    url=job_url,
                    job_id=job_id,
                )
                evaluation = evaluator(posting)
            except Exception as exc:
                reject(
                    job,
                    f"Resume evaluation failed safely: {type(exc).__name__}.",
                )
                assessed_count += 1
                continue

            assessed_count += 1
            _record_decision_metadata(job, evaluation)
            decision = getattr(evaluation, "decision", None)
            manual_review_reasons = tuple(getattr(decision, "manual_review_reasons", ()) or ())
            if (
                not getattr(evaluation, "eligible", False)
                or decision is None
                or not getattr(decision, "eligible", False)
                or manual_review_reasons
            ):
                reject(
                    job,
                    getattr(
                        evaluation,
                        "reason",
                        "Resume evaluation did not approve this job.",
                    ),
                )
                continue

            raw_score = getattr(decision, "score", None)
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                reject(job, "Resume evaluation returned an invalid match score.")
                continue
            if isinstance(raw_score, bool) or not isfinite(score):
                reject(job, "Resume evaluation returned an invalid match score.")
                continue

            profile, _ = _decision_metadata(evaluation)
            job["Resume Profile"] = profile
            job["Resume Match Score"] = score
            ranked.append((score, discovery_index, job))
    finally:
        if original_url:
            try:
                driver.get(original_url)
            except Exception:
                pass

    if cancelled:
        return JobSelection(
            selected_jobs=(),
            deferred_jobs=tuple(item[2] for item in ranked),
            rejected_jobs=tuple(rejected),
            assessed_count=assessed_count,
            cancelled=True,
        )

    ranked.sort(key=lambda item: (-item[0], item[1]))
    for rank, (_, _, job) in enumerate(ranked, start=1):
        job["Candidate Rank"] = rank
    selected = tuple(item[2] for item in ranked[:limit])
    deferred = tuple(item[2] for item in ranked[limit:])
    for job in selected:
        job["Selection Status"] = "selected"
    for job in deferred:
        job["Selection Status"] = "eligible_outside_job_limit"
        job["Selection Reason"] = (
            f"Resume-eligible but outside the top {limit} jobs by match score."
        )

    return JobSelection(
        selected_jobs=selected,
        deferred_jobs=deferred,
        rejected_jobs=tuple(rejected),
        assessed_count=assessed_count,
    )


def apply_to_job_url(
    driver,
    job: Mapping[str, Any],
    resume_service: ResumeService,
    *,
    run_mode: RunMode | str = RunMode.SUBMIT,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[ApplicationProgress], None] | None = None,
) -> ApplicationResult:
    """Prepare, upload, and submit one Dice Easy Apply job; fail closed on uncertainty."""

    require_dice_automation_authorized()
    mode = RunMode(run_mode)
    job_url = str(job.get("Job URL", ""))
    job_title = str(job.get("Job Title", "")).strip()
    job_id = str(job.get("Job ID", "")).strip()
    original_url = driver.current_url
    result = ApplicationResult(ApplicationStatus.FAILED, "Application did not complete.")
    navigated = False
    resume_selection_attempted = False
    try:
        if not _is_dice_url(job_url, job_detail=True):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Only HTTPS Dice job-detail URLs are accepted.",
            )
            return result
        if _cancellation_requested(cancel_requested):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Run cancelled before navigation.",
            )
            return result
        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.OPENING_JOB,
            "Opening Dice job details",
            job_title=job_title,
        )
        driver.get(job_url)
        navigated = True
        current_url = str(driver.current_url or "")
        if not _same_dice_job_detail_page(job_url, current_url):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Dice redirected to a different job detail; skipped to avoid applying "
                "to the wrong posting.",
            )
            return result
        description = _extract_job_description(driver)
        if not description:
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Dice job description could not be read; skipped to avoid a random application.",
            )
            return result

        try:
            posting = JobPosting(
                title=job_title,
                description=description,
                url=job_url,
                job_id=job_id,
            )
        except ValueError as exc:
            result = ApplicationResult(ApplicationStatus.SKIPPED, str(exc))
            return result

        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.EVALUATING_RESUME,
            "Evaluating full job description and resume fit",
            job_title=job_title,
        )
        evaluation = None
        preparation = None
        evaluator = getattr(resume_service, "evaluate", None)
        if mode is RunMode.PREVIEW:
            if not callable(evaluator):
                result = ApplicationResult(
                    ApplicationStatus.FAILED,
                    "Preview requires a side-effect-free resume evaluator.",
                )
                return result
            evaluation = evaluator(posting)
        elif callable(evaluator):
            evaluation = evaluator(posting)
        else:
            preparation = resume_service.prepare(posting)

        gate_outcome = evaluation if evaluation is not None else preparation
        profile, score = _decision_metadata(gate_outcome)
        _record_decision_metadata(job, gate_outcome)
        if gate_outcome is None or not getattr(gate_outcome, "eligible", False):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                getattr(gate_outcome, "reason", "Resume evaluation did not approve this job."),
                resume_profile=profile,
                match_score=score,
            )
            return result

        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.CHECKING_EASY_APPLY,
            "Checking Dice Easy Apply eligibility",
            job_title=job_title,
            resume_profile=profile,
        )
        apply_control = WebDriverWait(driver, 20).until(
            lambda current: _find_apply_control(current, job_url)
        )
        control_text = (apply_control.text or "").strip().lower()
        control_href = (apply_control.get_attribute("href") or "").strip()
        if "applied" in control_text or "application submitted" in control_text:
            result = ApplicationResult(
                ApplicationStatus.ALREADY_APPLIED,
                "Dice reports that this job was already applied to.",
                resume_profile=profile,
                match_score=score,
            )
            return result
        is_easy_apply = (
            not control_href and "easy apply" in control_text
        ) or _is_expected_dice_apply_target(control_href, job_url)
        if not is_easy_apply:
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Only the Dice Easy Apply wizard is supported; external Apply links are skipped.",
                resume_profile=profile,
                match_score=score,
            )
            return result
        if not apply_control.is_enabled():
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Dice Easy Apply is visible but not enabled.",
                resume_profile=profile,
                match_score=score,
            )
            return result
        if mode is RunMode.PREVIEW:
            result = ApplicationResult(
                ApplicationStatus.PREVIEW_READY,
                "Preview confirmed an eligible Dice Easy Apply job; Apply was not clicked.",
                resume_profile=profile,
                match_score=score,
            )
            return result

        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.PREPARING_RESUME,
            "Preparing the approved resume for this job",
            job_title=job_title,
            resume_profile=profile,
        )
        if preparation is None:
            prepare_selected = getattr(
                resume_service,
                (
                    "prepare_selected_for_verification"
                    if mode is RunMode.VERIFY_UPLOAD
                    else "prepare_selected"
                ),
                None,
            )
            if callable(prepare_selected) and evaluation is not None:
                decision = getattr(evaluation, "decision", evaluation)
                preparation = prepare_selected(posting, decision)
            else:
                preparation = resume_service.prepare(posting)
        profile, score = _decision_metadata(preparation)
        if (
            not getattr(preparation, "eligible", False)
            or getattr(preparation, "prepared", None) is None
        ):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                getattr(preparation, "reason", "Resume preparation did not approve this job."),
                resume_profile=profile,
                match_score=score,
            )
            return result
        prepared_path = preparation.prepared.path.resolve()
        if preparation.prepared.verification_fallback:
            resume_kind = "verify-only fallback"
        else:
            resume_kind = "generated" if preparation.prepared.tailored else "selected"
        if isinstance(job, dict):
            job["Tailored Resume"] = bool(preparation.prepared.tailored)
            job["Verification Resume Fallback"] = bool(
                preparation.prepared.verification_fallback
            )
        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.RESUME_READY,
            f"{resume_kind.title()} resume ready",
            job_title=job_title,
            resume_profile=profile,
            resume_filename=prepared_path.name,
            resume_kind=resume_kind,
        )

        def assert_prepared_resume_ready() -> None:
            guard = getattr(resume_service, "assert_prepared_resume_ready", None)
            if callable(guard):
                guard(posting, preparation.prepared)

        if _cancellation_requested(cancel_requested):
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                "Run cancelled before opening Dice Easy Apply.",
                resume_profile=profile,
                match_score=score,
            )
            return result
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            apply_control,
        )
        try:
            assert_prepared_resume_ready()
        except ResumeTailoringError as exc:
            result = ApplicationResult(
                ApplicationStatus.SKIPPED,
                str(exc),
                resume_profile=profile,
                match_score=score,
            )
            return result
        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.OPENING_WIZARD,
            "Opening Dice Easy Apply wizard",
            job_title=job_title,
            resume_profile=profile,
            resume_filename=prepared_path.name,
            resume_kind=resume_kind,
        )
        try:
            apply_control.click()
        except Exception:
            driver.execute_script("arguments[0].click();", apply_control)

        next_locator = (
            By.XPATH,
            "//button[not(@disabled) and (@type='submit' or @type='button') and "
            "(normalize-space(.)='Next' or .//span[normalize-space()='Next'])]",
        )
        submit_locator = (
            By.XPATH,
            "//button[not(@disabled) and (@type='submit' or @type='button') and "
            "(normalize-space(.)='Submit' or .//span[normalize-space()='Submit'])]",
        )
        resume_uploaded = False

        def mark_resume_selection_attempted() -> None:
            nonlocal resume_selection_attempted
            resume_selection_attempted = True

        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.VERIFYING_UPLOAD,
            "Waiting for the resume picker and verifying the selected filename",
            job_title=job_title,
            resume_profile=profile,
            resume_filename=prepared_path.name,
            resume_kind=resume_kind,
        )
        for _ in range(12):
            if not _is_expected_apply_context(str(driver.current_url or ""), job_url):
                result = ApplicationResult(
                    ApplicationStatus.SKIPPED,
                    "Apply navigation did not remain in this job's Dice Easy Apply context; "
                    "the resume was not selected.",
                    resume_profile=profile,
                    match_score=score,
                )
                return result

            if not resume_uploaded:
                if _cancellation_requested(cancel_requested):
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Run cancelled before selecting the resume file.",
                        resume_profile=profile,
                        match_score=score,
                    )
                    return result
                try:
                    found_input, upload_succeeded, upload_reason = _upload_resume_if_present(
                        driver,
                        str(prepared_path),
                        pre_upload=assert_prepared_resume_ready,
                        selection_callback=mark_resume_selection_attempted,
                    )
                except ResumeTailoringError as exc:
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        str(exc),
                        resume_profile=profile,
                        match_score=score,
                        resume_selection_attempted=resume_selection_attempted,
                    )
                    return result
                if found_input and not upload_succeeded:
                    result = ApplicationResult(
                        ApplicationStatus.FAILED,
                        upload_reason or "The intended resume could not be uploaded and verified.",
                        resume_profile=profile,
                        match_score=score,
                        resume_selection_attempted=resume_selection_attempted,
                    )
                    return result
                resume_uploaded = upload_succeeded
                if resume_uploaded:
                    _emit_application_progress(
                        progress_callback,
                        ApplicationProgressStage.RESUME_SELECTED,
                        "Resume selected in Dice; intended filename verified",
                        job_title=job_title,
                        resume_profile=profile,
                        resume_filename=prepared_path.name,
                        resume_kind=resume_kind,
                    )
                if resume_uploaded and mode is RunMode.VERIFY_UPLOAD:
                    result = ApplicationResult(
                        ApplicationStatus.UPLOAD_VERIFIED,
                        "The intended resume filename was verified; Next and Submit "
                        "were not clicked.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name,
                        resume_selection_attempted=True,
                    )
                    return result

            if mode is RunMode.VERIFY_UPLOAD:
                submit_visible = _visible_enabled(driver.find_elements(*submit_locator))
                next_visible = _visible_enabled(driver.find_elements(*next_locator))
                if submit_visible is not None or next_visible is not None:
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Dice did not expose a resume input on the initial wizard step; "
                        "verification mode never clicks Next or Submit.",
                        resume_profile=profile,
                        match_score=score,
                    )
                    return result
                time.sleep(0.5)
                continue

            submit_button = _visible_enabled(driver.find_elements(*submit_locator))
            if submit_button is not None:
                if not resume_uploaded:
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Dice did not expose a verifiable resume upload before Submit.",
                        resume_profile=profile,
                        match_score=score,
                    )
                    return result
                if _has_visible_screening_controls(driver):
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Visible screening questions or consent controls require manual review.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name,
                    )
                    return result
                if _cancellation_requested(cancel_requested):
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Run cancelled before Submit.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name,
                    )
                    return result
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", submit_button
                )
                try:
                    assert_prepared_resume_ready()
                except ResumeTailoringError as exc:
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        str(exc),
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name,
                    )
                    return result
                _emit_application_progress(
                    progress_callback,
                    ApplicationProgressStage.SUBMITTING,
                    "Submitting the verified Dice application",
                    job_title=job_title,
                    resume_profile=profile,
                    resume_filename=prepared_path.name,
                    resume_kind=resume_kind,
                )
                try:
                    submit_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", submit_button)
                try:
                    WebDriverWait(driver, 30, poll_frequency=0.4).until(_confirmation_present)
                except Exception:
                    result = ApplicationResult(
                        ApplicationStatus.FAILED,
                        "Submit was clicked, but Dice did not confirm the application.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name,
                    )
                    return result
                _emit_application_progress(
                    progress_callback,
                    ApplicationProgressStage.SUBMISSION_CONFIRMED,
                    "Dice confirmed the application submission",
                    job_title=job_title,
                    status=ApplicationStatus.APPLIED.value,
                    resume_profile=profile,
                    resume_filename=prepared_path.name,
                    resume_kind=resume_kind,
                )
                result = ApplicationResult(
                    ApplicationStatus.APPLIED,
                    "Dice confirmed the application submission.",
                    resume_profile=profile,
                    match_score=score,
                    resume_filename=prepared_path.name,
                )
                return result

            next_button = _visible_enabled(driver.find_elements(*next_locator))
            if next_button is not None:
                if _has_visible_screening_controls(driver):
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Visible screening questions or consent controls require manual review.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name if resume_uploaded else "",
                    )
                    return result
                if _cancellation_requested(cancel_requested):
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        "Run cancelled before Next.",
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name if resume_uploaded else "",
                    )
                    return result
                try:
                    assert_prepared_resume_ready()
                except ResumeTailoringError as exc:
                    result = ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        str(exc),
                        resume_profile=profile,
                        match_score=score,
                        resume_filename=prepared_path.name if resume_uploaded else "",
                    )
                    return result
                _emit_application_progress(
                    progress_callback,
                    ApplicationProgressStage.ADVANCING_WIZARD,
                    "Advancing to the next verified Dice wizard step",
                    job_title=job_title,
                    resume_profile=profile,
                    resume_filename=prepared_path.name if resume_uploaded else "",
                    resume_kind=resume_kind,
                )
                try:
                    next_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", next_button)
                time.sleep(0.6)
                continue
            time.sleep(0.5)

        result = ApplicationResult(
            ApplicationStatus.FAILED,
            "Dice Easy Apply did not reach a confirmed Submit step.",
            resume_profile=profile,
            match_score=score,
            resume_filename=prepared_path.name if resume_uploaded else "",
        )
        return result
    except Exception as exc:
        result = ApplicationResult(
            ApplicationStatus.FAILED,
            f"Application flow failed: {type(exc).__name__}.",
            resume_selection_attempted=resume_selection_attempted,
        )
        return result
    finally:
        _record_resume_metadata(job, result)
        _emit_application_progress(
            progress_callback,
            ApplicationProgressStage.COMPLETED,
            result.reason,
            job_title=job_title,
            status=result.status.value,
            resume_profile=result.resume_profile,
            resume_filename=result.resume_filename,
        )
        if navigated and original_url:
            try:
                driver.get(original_url)
            except Exception:
                pass


def fetch_jobs_with_requests(
    driver,
    search_query,
    include_keywords=None,
    exclude_keywords=None,
    *,
    max_pages=None,
    max_included_jobs=None,
):
    """
    Use the existing browser instance to fetch job listings.
    """
    require_dice_automation_authorized()
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be at least 1 when provided.")
    if max_included_jobs is not None and max_included_jobs < 1:
        raise ValueError("max_included_jobs must be at least 1 when provided.")
    print(f"Fetching jobs for query: {search_query}")

    # Format search parameters for URL
    encoded_query = quote(search_query)

    # Updated URL structure
    base_url = f"https://www.dice.com/jobs?filters.employmentType=CONTRACTS&filters.postedDate=ONE&q={encoded_query}"

    included_jobs = []
    excluded_jobs = []
    total_jobs_found = 0

    # Create WebDriverWait objects with different timeout values
    short_wait = WebDriverWait(driver, 20)
    medium_wait = WebDriverWait(driver, 30)
    card_wait = WebDriverWait(driver, 10)

    try:
        # First load the initial page
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Loading search results for query: '{search_query}'...")
                driver.get(base_url)
                short_wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Error loading initial page. Retry {attempt + 1}/{max_retries}...")
                else:
                    print(f"Failed to load initial page after {max_retries} attempts.")
                    raise e

        # Get total jobs count
        total_pages = 1
        try:
            print("Looking for job count element...")

            # Wait for the job count element with flexibility in the class name
            job_count_element = medium_wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//p[contains(@class, 'text-neutral-900') and contains(text(), 'results')]",
                    )
                )
            )

            total_jobs_text = job_count_element.text
            print(f"Found job count text: '{total_jobs_text}'")

            total_jobs_match = re.search(r"(\d+)\s+results", total_jobs_text)

            if total_jobs_match:
                total_jobs = int(total_jobs_match.group(1))
                print(f"Total jobs for query '{search_query}': {total_jobs}")

                # Dice's page size changes over time. Derive it from the first page instead
                # of assuming 20, which otherwise causes requests for empty trailing pages.
                try:
                    card_wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "div[data-id][data-job-guid]")
                        )
                    )
                except Exception:
                    pass
                first_page_size = len(
                    driver.find_elements(By.CSS_SELECTOR, "div[data-id][data-job-guid]")
                )
                jobs_per_page = first_page_size or 20
                total_pages = _bounded_page_count(
                    total_jobs,
                    first_page_size,
                    max_pages=max_pages,
                )
                print(f"Will process {total_pages} pages ({jobs_per_page} jobs per page)")
            else:
                print(f"Could not extract job count from: {total_jobs_text}")
                total_pages = 3  # Default to 3 pages
                if max_pages is not None:
                    total_pages = min(total_pages, max_pages)

        except Exception as e:
            print(f"Could not find total job count, defaulting to 3 pages: {str(e)}")
            total_pages = 3
            if max_pages is not None:
                total_pages = min(total_pages, max_pages)

        # Process each page
        for page in range(1, total_pages + 1):
            current_url = base_url if page == 1 else f"{base_url}&page={page}"
            print(f"Processing page {page}/{total_pages}: {current_url}")

            if page > 1:  # Only need to navigate if not on first page
                try:
                    driver.get(current_url)
                    short_wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                except Exception as e:
                    print(f"Error loading page {page}: {e}")
                    break

            # Wait for job cards to appear with a more specific selector based on example
            try:
                print("Waiting for job cards to load...")

                # NEW APPROACH: Wait specifically for job cards using data attributes
                card_wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id][data-job-guid]"))
                )

                # Add a small delay to ensure dynamic content is fully rendered
                time.sleep(2)

                # Get all job cards using the data-id and data-job-guid attributes
                job_cards = driver.find_elements(By.CSS_SELECTOR, "div[data-id][data-job-guid]")

                if not job_cards:
                    print(f"No job cards found on page {page}")
                    break

                print(f"Found {len(job_cards)} jobs on page {page}")

                # Process each job card
                for card_index, card in enumerate(job_cards):
                    try:
                        # Get job ID and URL from data attributes
                        job_id = card.get_attribute("data-id")
                        job_guid = card.get_attribute("data-job-guid")
                        if not job_guid:
                            print(f"Missing job_guid on card {card_index}")
                            continue

                        job_url = f"https://www.dice.com/job-detail/{job_guid}"

                        # Extract job title - using the exact classes from example
                        job_title_element = card.find_element(
                            By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']"
                        )
                        job_title = (
                            job_title_element.text.strip() if job_title_element else "Unknown"
                        )

                        # Extract company name - using the exact structure from example
                        company_element = card.find_element(
                            By.CSS_SELECTOR, "a[href*='company-profile'] p"
                        )
                        company_name = (
                            company_element.text.strip() if company_element else "Unknown"
                        )

                        # Extract location - first text paragraph with the specified class
                        location_elements = card.find_elements(
                            By.CSS_SELECTOR, "p.text-sm.font-normal.text-zinc-600"
                        )
                        job_location = (
                            location_elements[0].text.strip() if location_elements else "Unknown"
                        )

                        # Extract employment type from the box with specific ID
                        job_employment_type = (
                            "Contract"  # Default since we're filtering for contracts
                        )
                        try:
                            emp_type_element = card.find_element(
                                By.CSS_SELECTOR, "p#employmentType-label"
                            )
                            if emp_type_element:
                                job_employment_type = emp_type_element.text.strip()
                        except:
                            # Fallback: look for any box containing "Contract"
                            try:
                                box_elements = card.find_elements(By.CSS_SELECTOR, "div.box p")
                                for element in box_elements:
                                    if "Contract" in element.text:
                                        job_employment_type = element.text.strip()
                                        break
                            except:
                                pass

                        # Posted date is always "Today" since we filter for last 24 hours
                        job_posted_date = "Today"

                        # Create job entry
                        job_entry = {
                            "Job ID": job_id or job_guid,
                            "Job Title": job_title,
                            "Job URL": job_url,
                            "Company": company_name,
                            "Location": job_location,
                            "Employment Type": job_employment_type,
                            "Posted Date": job_posted_date,
                            "Applied": False,
                        }

                        # Apply filtering
                        include_job = True
                        exclusion_reason = ""
                        job_title_lower = job_title.lower()

                        # Check exclude keywords
                        if exclude_keywords and any(
                            keyword.lower() in job_title_lower for keyword in exclude_keywords
                        ):
                            matching_keywords = [
                                kw for kw in exclude_keywords if kw.lower() in job_title_lower
                            ]
                            exclusion_reason = (
                                f"Contains excluded keywords: {', '.join(matching_keywords)}"
                            )
                            include_job = False

                        # Check include keywords
                        if include_keywords and not any(
                            keyword.lower() in job_title_lower for keyword in include_keywords
                        ):
                            exclusion_reason = (
                                f"Missing required keywords: {', '.join(include_keywords)}"
                            )
                            include_job = False

                        if include_job:
                            included_jobs.append(job_entry)
                            if (
                                max_included_jobs is not None
                                and len(included_jobs) >= max_included_jobs
                            ):
                                break
                        else:
                            job_entry["Exclusion Reason"] = exclusion_reason
                            excluded_jobs.append(job_entry)

                    except Exception as e:
                        print(f"Error processing job card {card_index} on page {page}: {str(e)}")
                        continue

                total_jobs_found += len(job_cards)
                if max_included_jobs is not None and len(included_jobs) >= max_included_jobs:
                    print(
                        f"Reached candidate limit of {max_included_jobs} for query '{search_query}'"
                    )
                    break

            except Exception as e:
                print(f"Error processing job cards on page {page}: {str(e)}")
                # Stop at the first unreadable/empty page instead of waiting on trailing pages.
                break

    except Exception as e:
        print(f"Error during job fetching: {str(e)}")

    print(f"Total jobs processed: {total_jobs_found}")
    print(f"Jobs included after filtering: {len(included_jobs)}")
    print(f"Jobs excluded after filtering: {len(excluded_jobs)}")

    return included_jobs, excluded_jobs


def save_to_excel(job_data, filename="job_application_report.xlsx"):
    """
    Saves job data to an Excel file.
    """
    try:
        df = pd.DataFrame(job_data["jobs"])
        df.to_excel(filename, index=False)
        print(f"Job application report saved to {filename}")
    except Exception as e:
        print(f"Error saving to Excel: {e}")


def main():
    """Keep the supported entry point explicit and avoid a second unsafe workflow."""

    raise SystemExit("Run the configured Tkinter application with: python run.py")


if __name__ == "__main__":
    main()
