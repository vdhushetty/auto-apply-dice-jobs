from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import core.main_script as main_script
from core.authorization import DiceAuthorizationError
from core.main_script import (
    ApplicationProgressStage,
    ApplicationStatus,
    RunMode,
    apply_to_job_url,
    build_diverse_candidate_pool,
    candidate_bucket_limits,
    fetch_jobs_with_requests,
    rank_eligible_jobs,
)
from core.resumes.models import (
    CloudProfile,
    MatchDecision,
    PreparedResume,
    ResumePreparation,
    ResumeTailoringError,
)


class FakeDriver:
    def __init__(self) -> None:
        self.current_url = "https://www.dice.com/jobs?q=data"
        self.visited: list[str] = []

    def get(self, url: str) -> None:
        self.current_url = url
        self.visited.append(url)


class RedirectingJobDriver(FakeDriver):
    def get(self, url: str) -> None:
        self.visited.append(url)
        if "/job-detail/" in url:
            self.current_url = "https://www.dice.com/job-detail/different-job"
        else:
            self.current_url = url


class FakeElement:
    def __init__(
        self,
        text: str = "",
        href: str = "",
        *,
        enabled: bool = True,
        displayed: bool = True,
        accepts_file: bool = True,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.href = href
        self.enabled = enabled
        self.displayed = displayed
        self.accepts_file = accepts_file
        self.clicked = False
        self.value = ""
        self.selected_file_name = ""
        self.send_keys_calls = 0
        self.attributes = attributes or {}

    def is_displayed(self) -> bool:
        return self.displayed

    def is_enabled(self) -> bool:
        return self.enabled

    def get_attribute(self, name: str) -> str:
        if name == "href":
            return self.href
        if name == "value":
            return self.value
        return self.attributes.get(name, "")

    def click(self) -> None:
        self.clicked = True

    def send_keys(self, value: str) -> None:
        self.send_keys_calls += 1
        if self.accepts_file:
            self.value = value
            self.selected_file_name = Path(value).name


class DescriptionElement:
    def __init__(self, *, text: str = "", attributes: dict[str, str] | None = None) -> None:
        self.text = text
        self.attributes = attributes or {}

    def get_attribute(self, name: str) -> str:
        return self.attributes.get(name, "")


class DescriptionDriver(FakeDriver):
    def __init__(
        self,
        elements: dict[str, list[DescriptionElement]],
        *,
        current_url: str = "https://www.dice.com/job-detail/current-job",
    ) -> None:
        super().__init__()
        self.elements = elements
        self.current_url = current_url

    def find_elements(self, by: str, selector: str) -> list[DescriptionElement]:
        return self.elements.get(selector, [])


class WizardDriver(FakeDriver):
    def __init__(
        self,
        *,
        has_file_input: bool,
        apply_text: str = "Easy Apply",
        apply_enabled: bool = True,
        accepts_file: bool = True,
        has_next: bool = False,
        has_screening_control: bool = False,
        confirmed: bool = False,
        file_input_context: str = "",
    ) -> None:
        super().__init__()
        self.apply_control = FakeElement(apply_text, enabled=apply_enabled)
        self.submit_button = FakeElement("Submit")
        self.next_button = FakeElement("Next") if has_next else None
        self.file_input = (
            FakeElement(accepts_file=accepts_file, attributes={"name": "resume"})
            if has_file_input
            else None
        )
        self.screening_control = FakeElement() if has_screening_control else None
        self.confirmation = FakeElement("Application submitted") if confirmed else None
        self.file_input_context = file_input_context
        self.page_source = ""

    def find_elements(self, by: str, selector: str) -> list[FakeElement]:
        if selector == 'button[data-testid="apply-button"], a[data-testid="apply-button"]':
            return [self.apply_control]
        if selector == 'input[type="file"]':
            return [self.file_input] if self.file_input is not None else []
        if selector in {
            '[data-testid="job-application-success-card"]',
            '[data-testid="application-success"]',
            "header.post-apply-banner h1",
        }:
            return [self.confirmation] if self.confirmation is not None else []
        if selector in {
            'input:not([type="hidden"]):not([type="file"]):not([type="submit"])'
            ':not([type="button"])',
            "select",
            "textarea",
            '[role="checkbox"]',
            '[role="radio"]',
            '[contenteditable="true"]',
        }:
            return [self.screening_control] if self.screening_control is not None else []
        if "Submit" in selector:
            return [self.submit_button]
        if "Next" in selector:
            return [self.next_button] if self.next_button is not None else []
        return []

    def execute_script(self, script: str, *args: Any) -> Any:
        if "files = arguments[0].files" in script and args:
            return args[0].selected_file_name
        if "const el = arguments[0]" in script:
            return self.file_input_context
        if "click" in script and args:
            args[0].click()
        return None


class ImmediateWait:
    def __init__(self, driver: FakeDriver, *args: Any, **kwargs: Any) -> None:
        self.driver = driver

    def until(self, predicate):  # type: ignore[no-untyped-def]
        value = predicate(self.driver)
        if value:
            return value
        raise TimeoutError("condition not met")


class NavigatingApplyElement(FakeElement):
    def __init__(self, driver: FakeDriver, destination: str) -> None:
        super().__init__("Easy Apply")
        self.driver = driver
        self.destination = destination

    def click(self) -> None:
        super().click()
        self.driver.current_url = self.destination


class MultipleFileInputDriver(WizardDriver):
    def __init__(self, file_inputs: list[FakeElement]) -> None:
        super().__init__(has_file_input=False, has_next=True)
        self.file_inputs = file_inputs

    def find_elements(self, by: str, selector: str) -> list[FakeElement]:
        if selector == 'input[type="file"]':
            return self.file_inputs
        return super().find_elements(by, selector)


class SearchCard:
    def __init__(self, index: int) -> None:
        self.index = index

    def get_attribute(self, name: str) -> str:
        if name == "data-id":
            return f"id-{self.index}"
        if name == "data-job-guid":
            return f"guid-{self.index}"
        return ""

    def find_element(self, by: str, selector: str) -> FakeElement:
        if selector == "a[data-testid='job-search-job-detail-link']":
            return FakeElement(f"Job {self.index}")
        if selector == "a[href*='company-profile'] p":
            return FakeElement("Example Company")
        if selector == "p#employmentType-label":
            return FakeElement("Contract")
        raise RuntimeError(f"Unexpected selector: {selector}")

    def find_elements(self, by: str, selector: str) -> list[FakeElement]:
        if selector == "p.text-sm.font-normal.text-zinc-600":
            return [FakeElement("Remote")]
        return []


class SearchDriver(FakeDriver):
    def __init__(self, first_page_size: int) -> None:
        super().__init__()
        self.cards = [SearchCard(index) for index in range(first_page_size)]

    def find_element(self, by: str, selector: str):  # type: ignore[no-untyped-def]
        if by == "tag name" and selector == "body":
            return FakeElement("ready")
        if by == "xpath":
            return FakeElement("102 results")
        if by == "css selector" and selector == "div[data-id][data-job-guid]":
            cards = self.find_elements(by, selector)
            if cards:
                return cards[0]
        raise RuntimeError("element not found")

    def find_elements(self, by: str, selector: str):  # type: ignore[no-untyped-def]
        if selector == "div[data-id][data-job-guid]" and "page=2" not in self.current_url:
            return self.cards
        return []


@dataclass
class SkipService:
    def prepare(self, job):  # type: ignore[no-untyped-def]
        return ResumePreparation(eligible=False, reason="match below threshold")


@dataclass
class PreparedService:
    resume_path: Path

    def prepare(self, job):  # type: ignore[no-untyped-def]
        decision = MatchDecision(
            selected_profile=CloudProfile.AWS,
            selected_path=self.resume_path,
            score=80,
            threshold=35,
            eligible=True,
        )
        return ResumePreparation(
            eligible=True,
            reason="eligible",
            decision=decision,
            prepared=PreparedResume(
                path=self.resume_path,
                decision=decision,
                tailored=False,
            ),
        )


@dataclass
class VerificationFallbackService:
    resume_path: Path
    verify_prepare_called: bool = False

    def evaluate(self, job):  # type: ignore[no-untyped-def]
        decision = MatchDecision(
            selected_profile=CloudProfile.AWS,
            selected_path=self.resume_path,
            score=80,
            threshold=35,
            eligible=True,
        )
        return ResumePreparation(eligible=True, reason="eligible", decision=decision)

    def prepare_selected(self, job, decision):  # type: ignore[no-untyped-def]
        raise AssertionError("verification must use its explicit no-submit preparation path")

    def prepare_selected_for_verification(self, job, decision):  # type: ignore[no-untyped-def]
        self.verify_prepare_called = True
        return ResumePreparation(
            eligible=True,
            reason="Verify-only fallback",
            decision=decision,
            prepared=PreparedResume(
                path=self.resume_path,
                decision=decision,
                tailored=False,
                verification_fallback=True,
            ),
        )


@dataclass
class GuardedPreparedService(PreparedService):
    fail_on_guard_call: int = 1
    guard_calls: int = 0

    def assert_prepared_resume_ready(self, job, prepared):  # type: ignore[no-untyped-def]
        self.guard_calls += 1
        if self.guard_calls == self.fail_on_guard_call:
            raise ResumeTailoringError("AI resume integrity check no longer matches.")
        return "ready-digest"


@dataclass
class EvaluatingService:
    evaluate_called: bool = False
    prepare_called: bool = False

    def evaluate(self, job):  # type: ignore[no-untyped-def]
        self.evaluate_called = True
        decision = MatchDecision(
            selected_profile=CloudProfile.AWS,
            selected_path=Path("/tmp/aws.docx"),
            score=80,
            threshold=35,
            eligible=True,
        )
        return ResumePreparation(
            eligible=True,
            reason="eligible",
            decision=decision,
        )

    def prepare(self, job):  # type: ignore[no-untyped-def]
        self.prepare_called = True
        raise AssertionError("preview must not prepare a resume")


@dataclass
class RankingService:
    evaluations: dict[str, ResumePreparation]
    postings: list[Any]

    def evaluate(self, job):  # type: ignore[no-untyped-def]
        self.postings.append(job)
        return self.evaluations[job.title]

    def prepare(self, job):  # type: ignore[no-untyped-def]
        raise AssertionError("candidate ranking must never prepare a resume")


def ranking_evaluation(
    score: float,
    *,
    eligible: bool = True,
    manual_review_reasons: tuple[str, ...] = (),
) -> ResumePreparation:
    decision = MatchDecision(
        selected_profile=CloudProfile.AWS,
        selected_path=Path("/tmp/aws.docx"),
        score=score,
        threshold=35,
        eligible=eligible,
        manual_review_reasons=manual_review_reasons,
    )
    return ResumePreparation(
        eligible=eligible,
        reason=decision.reason,
        decision=decision,
    )


@pytest.fixture(autouse=True)
def authorize_dice_automation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DICE_AUTOMATION_AUTHORIZED", "true")


def test_mismatch_never_reaches_apply_control(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    driver = FakeDriver()
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    apply_control_called = False

    def forbidden_control(current):  # type: ignore[no-untyped-def]
        nonlocal apply_control_called
        apply_control_called = True
        raise AssertionError("apply control must not be inspected")

    monkeypatch.setattr(main_script, "_find_apply_control", forbidden_control)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/skip-flow",
    }

    result = apply_to_job_url(driver, job, SkipService())  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert not apply_control_called
    assert driver.current_url == "https://www.dice.com/jobs?q=data"
    assert driver.visited[-1] == "https://www.dice.com/jobs?q=data"


def test_missing_resume_picker_prevents_submit(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=False)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/no-picker",
    }

    result = apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert "resume upload" in result.reason
    assert not driver.submit_button.clicked
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


def test_unconfirmed_submit_is_failure(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    driver.page_source = "application submitted"
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/no-confirmation",
    }

    result = apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.FAILED
    assert "did not confirm" in result.reason
    assert driver.submit_button.clicked
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


def test_preview_evaluates_without_clicking_apply(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    driver = WizardDriver(has_file_input=False)
    service = EvaluatingService()
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/preview",
    }

    result = apply_to_job_url(driver, job, service, run_mode=RunMode.PREVIEW)  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.PREVIEW_READY
    assert service.evaluate_called
    assert not service.prepare_called
    assert not driver.apply_control.clicked
    assert not driver.submit_button.clicked
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


def test_verify_upload_never_clicks_next_or_submit(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/upload-check",
    }

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert driver.apply_control.clicked
    assert driver.file_input is not None
    assert driver.file_input.selected_file_name == resume.name
    assert driver.next_button is not None and not driver.next_button.clicked
    assert not driver.submit_button.clicked
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


@pytest.mark.parametrize(
    "destination",
    [
        "https://www.dice.com/profile/info",
        "https://www.dice.com/job-applications/different-job/start-apply",
        "https://www.dice.com/job-applications/intended-job/wizard/success",
    ],
)
def test_verify_never_selects_a_file_outside_the_intended_job_context(
    monkeypatch,
    tmp_path: Path,
    destination: str,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    driver.apply_control = NavigatingApplyElement(driver, destination)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/intended-job",
    }

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.SKIPPED
    assert "this job's Dice Easy Apply context" in result.reason
    assert driver.file_input is not None and not driver.file_input.selected_file_name
    assert driver.next_button is not None and not driver.next_button.clicked
    assert not driver.submit_button.clicked


def test_verify_accepts_the_intended_start_apply_url(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    driver.apply_control = NavigatingApplyElement(
        driver,
        "https://www.dice.com/job-applications/intended-job/start-apply",
    )
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/intended-job",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert driver.file_input is not None
    assert driver.file_input.selected_file_name == resume.name


def test_easy_apply_text_does_not_authorize_an_external_anchor(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    driver.apply_control = FakeElement("Easy Apply", href="https://example.com/apply")
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/external-anchor",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.SKIPPED
    assert not driver.apply_control.clicked
    assert driver.file_input is not None and not driver.file_input.selected_file_name


def test_current_dice_login_wrapper_is_accepted_only_for_the_same_job(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    driver.apply_control = FakeElement(
        "Apply Now",
        href=(
            "https://www.dice.com/dashboard/login?redirectUrl="
            "%2Fjob-applications%2Fwrapped-job%2Fwizard"
        ),
    )
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/wrapped-job",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert driver.file_input is not None
    assert driver.file_input.selected_file_name == resume.name


@pytest.mark.parametrize("suffix", ("applied", "success", "unexpected"))
def test_post_apply_wizard_routes_are_not_active_upload_contexts(suffix: str) -> None:
    job_url = "https://www.dice.com/job-detail/intended-job"

    assert not main_script._is_expected_dice_application_url(
        f"https://www.dice.com/job-applications/intended-job/wizard/{suffix}",
        job_url,
    )
    assert not main_script._is_expected_dice_apply_target(
        "https://www.dice.com/dashboard/login?redirectUrl="
        f"%2Fjob-applications%2Fintended-job%2Fwizard%2F{suffix}",
        job_url,
    )


def test_resume_selection_ignores_a_non_resume_file_input(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    cover_letter = FakeElement(attributes={"name": "coverLetter"})
    resume_input = FakeElement(attributes={"aria-label": "Upload resume"})
    driver = MultipleFileInputDriver([cover_letter, resume_input])
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/scoped-resume",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert not cover_letter.selected_file_name
    assert resume_input.selected_file_name == resume.name


def test_camel_case_resume_input_descriptor_is_recognized(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    resume_input = FakeElement(attributes={"data-testid": "resumeFileInput"})
    driver = MultipleFileInputDriver([resume_input])
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/camel-case-resume",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert resume_input.selected_file_name == resume.name


def test_ambiguous_resume_file_inputs_fail_closed(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    first = FakeElement(attributes={"name": "resume"})
    second = FakeElement(attributes={"aria-label": "Resume upload"})
    driver = MultipleFileInputDriver([first, second])
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "AWS Engineer",
            "Job URL": "https://www.dice.com/job-detail/ambiguous-resume",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.FAILED
    assert not result.resume_selection_attempted
    assert not first.selected_file_name
    assert not second.selected_file_name


def test_integrity_drift_before_apply_is_skipped(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "ai.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    service = GuardedPreparedService(resume, fail_on_guard_call=1)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/guard-before-apply",
    }

    result = apply_to_job_url(driver, job, service)  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert "integrity check no longer matches" in result.reason
    assert service.guard_calls == 1
    assert not driver.apply_control.clicked
    assert driver.file_input is not None and not driver.file_input.selected_file_name


def test_integrity_drift_immediately_before_upload_is_skipped(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "ai.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    service = GuardedPreparedService(resume, fail_on_guard_call=2)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/guard-before-upload",
    }

    result = apply_to_job_url(driver, job, service)  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert "integrity check no longer matches" in result.reason
    assert service.guard_calls == 2
    assert driver.apply_control.clicked
    assert driver.file_input is not None and not driver.file_input.selected_file_name


def test_integrity_is_checked_after_browser_filename_verification(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "ai.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    service = GuardedPreparedService(resume, fail_on_guard_call=3)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/guard-after-upload",
    }

    result = apply_to_job_url(
        driver,
        job,
        service,  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.SKIPPED
    assert result.resume_selection_attempted
    assert service.guard_calls == 3
    assert driver.file_input is not None and driver.file_input.selected_file_name == resume.name
    assert not driver.submit_button.clicked


def test_integrity_is_checked_again_immediately_before_submit(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "ai.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    service = GuardedPreparedService(resume, fail_on_guard_call=4)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/guard-before-submit",
    }

    result = apply_to_job_url(driver, job, service)  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert service.guard_calls == 4
    assert driver.file_input is not None and driver.file_input.selected_file_name == resume.name
    assert not driver.submit_button.clicked


def test_stale_page_text_cannot_verify_upload(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, accepts_file=False)
    driver.page_source = f"Previously uploaded: {resume.name}"
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/stale-upload",
    }

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.FAILED
    assert result.resume_selection_attempted
    assert "did not accept or report" in result.reason
    assert driver.file_input is not None and driver.file_input.send_keys_calls == 1
    assert not driver.submit_button.clicked


def test_resume_picker_uses_nearby_resume_prompt_for_generic_input(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(
        has_file_input=True,
        has_next=True,
        file_input_context="Upload your resume or CV to continue",
    )
    assert driver.file_input is not None
    driver.file_input.attributes = {"name": "attachment"}
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {"Job Title": "AWS Engineer", "Job URL": "https://www.dice.com/job-detail/context"},
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert driver.file_input.send_keys_calls == 1
    assert not driver.next_button.clicked
    assert not driver.submit_button.clicked


def test_unique_generic_dice_document_input_is_verified_as_resume_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    assert driver.file_input is not None
    driver.file_input.attributes = {
        "name": "attachment",
        "id": "file-upload",
        "data-testid": "generic-file-picker",
        "accept": ".pdf,.doc,.docx,.rtf,.txt",
    }
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {"Job Title": "AWS Engineer", "Job URL": "https://www.dice.com/job-detail/unlabeled"},
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert driver.file_input.send_keys_calls == 1
    assert not driver.next_button.clicked
    assert not driver.submit_button.clicked


def test_generic_file_input_with_incomplete_document_contract_stays_unselected(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    assert driver.file_input is not None
    driver.file_input.attributes = {"name": "attachment", "accept": ".pdf"}
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)

    result = apply_to_job_url(
        driver,
        {"Job Title": "AWS Engineer", "Job URL": "https://www.dice.com/job-detail/unlabeled"},
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.FAILED
    assert "none could be safely identified" in result.reason
    assert "input-1(name=attachment" in result.reason
    assert str(tmp_path) not in result.reason
    assert not driver.next_button.clicked
    assert not driver.submit_button.clicked


def test_disabled_already_applied_control_is_detected(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(
        has_file_input=False,
        apply_text="Applied",
        apply_enabled=False,
    )
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/already-applied",
    }

    result = apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.ALREADY_APPLIED
    assert not driver.apply_control.clicked


def test_screening_controls_prevent_submit(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_screening_control=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/screening",
    }

    result = apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert "manual review" in result.reason
    assert not driver.submit_button.clicked


def test_cancellation_is_checked_before_apply_click(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    checks = iter((False, True))
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/cancelled",
    }

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        cancel_requested=lambda: next(checks),
    )

    assert result.status is ApplicationStatus.SKIPPED
    assert "cancelled" in result.reason.lower()
    assert not driver.apply_control.clicked
    assert not driver.submit_button.clicked


def test_invalid_job_url_is_rejected_before_navigation(tmp_path: Path) -> None:
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = FakeDriver()
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://example.com/job-detail/not-dice",
    }

    result = apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]

    assert result.status is ApplicationStatus.SKIPPED
    assert driver.visited == []


def test_redirected_job_is_rejected_before_description_or_apply(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    driver = RedirectingJobDriver()
    resume = tmp_path / "aws.docx"
    resume.touch()

    def unexpected_description(current):  # type: ignore[no-untyped-def]
        raise AssertionError("redirected job description must not be used")

    monkeypatch.setattr(main_script, "_extract_job_description", unexpected_description)

    result = apply_to_job_url(
        driver,
        {
            "Job Title": "Intended Job",
            "Job URL": "https://www.dice.com/job-detail/intended-job",
        },
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
    )

    assert result.status is ApplicationStatus.SKIPPED
    assert "different job detail" in result.reason
    assert driver.visited == [
        "https://www.dice.com/job-detail/intended-job",
        "https://www.dice.com/jobs?q=data",
    ]


def test_live_adapters_require_authorization(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DICE_AUTOMATION_AUTHORIZED", raising=False)
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = FakeDriver()
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/not-authorized",
    }

    with pytest.raises(DiceAuthorizationError):
        apply_to_job_url(driver, job, PreparedService(resume))  # type: ignore[arg-type]
    with pytest.raises(DiceAuthorizationError):
        fetch_jobs_with_requests(driver, "AWS Engineer")

    assert driver.visited == []


def test_verify_upload_emits_secret_free_resume_and_confirmation_progress(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    events = []
    job = {
        "Job Title": "AWS\nEngineer sk-proj-1234567890",
        "Job URL": "https://www.dice.com/job-detail/observability",
    }

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
        progress_callback=events.append,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    stages = [event.stage for event in events]
    assert stages == [
        ApplicationProgressStage.OPENING_JOB,
        ApplicationProgressStage.EVALUATING_RESUME,
        ApplicationProgressStage.CHECKING_EASY_APPLY,
        ApplicationProgressStage.PREPARING_RESUME,
        ApplicationProgressStage.RESUME_READY,
        ApplicationProgressStage.OPENING_WIZARD,
        ApplicationProgressStage.VERIFYING_UPLOAD,
        ApplicationProgressStage.RESUME_SELECTED,
        ApplicationProgressStage.COMPLETED,
    ]
    resume_event = next(
        event for event in events if event.stage is ApplicationProgressStage.RESUME_READY
    )
    assert resume_event.resume_filename == "aws.docx"
    assert resume_event.resume_kind == "selected"
    assert str(tmp_path) not in repr(events)
    assert "sk-proj" not in repr(events)
    assert all("\n" not in event.job_title for event in events)
    assert events[-1].status == ApplicationStatus.UPLOAD_VERIFIED.value


def test_verify_upload_uses_explicit_no_submit_resume_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "base.docx"
    resume.touch()
    service = VerificationFallbackService(resume)
    driver = WizardDriver(has_file_input=True, has_next=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    events = []

    result = apply_to_job_url(
        driver,
        {"Job Title": "AWS Engineer", "Job URL": "https://www.dice.com/job-detail/verify"},
        service,  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
        progress_callback=events.append,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED
    assert service.verify_prepare_called
    ready_event = next(
        event for event in events if event.stage is ApplicationProgressStage.RESUME_READY
    )
    assert ready_event.resume_kind == "verify-only fallback"


def test_observability_callback_failure_never_changes_application_result(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    resume = tmp_path / "aws.docx"
    resume.touch()
    driver = WizardDriver(has_file_input=True, has_next=True)
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    job = {
        "Job Title": "AWS Engineer",
        "Job URL": "https://www.dice.com/job-detail/observer-failure",
    }

    def broken_observer(event):  # type: ignore[no-untyped-def]
        raise RuntimeError("UI closed")

    result = apply_to_job_url(
        driver,
        job,
        PreparedService(resume),  # type: ignore[arg-type]
        run_mode=RunMode.VERIFY_UPLOAD,
        progress_callback=broken_observer,
    )

    assert result.status is ApplicationStatus.UPLOAD_VERIFIED


def test_diverse_candidate_pool_is_bounded_stable_and_round_robin() -> None:
    shared = {
        "Job Title": "Shared",
        "Job URL": "https://www.dice.com/job-detail/shared",
    }
    buckets = [
        [
            {"Job Title": "A1", "Job URL": "https://www.dice.com/job-detail/a1"},
            {"Job Title": "A2", "Job URL": "https://www.dice.com/job-detail/a2"},
        ],
        [
            {"Job Title": "B1", "Job URL": "https://www.dice.com/job-detail/b1"},
            shared,
        ],
        [
            {"Job Title": "C1", "Job URL": "https://www.dice.com/job-detail/c1"},
            shared,
        ],
    ]

    pool = build_diverse_candidate_pool(
        buckets,
        application_limit=1,
        pool_multiplier=4,
    )

    assert [job["Job Title"] for job in pool] == ["A1", "B1", "C1", "A2"]


def test_candidate_budget_is_even_and_verify_upload_includes_each_query() -> None:
    assert candidate_bucket_limits(6, application_limit=10) == (7, 7, 7, 7, 6, 6)
    assert candidate_bucket_limits(6, application_limit=1) == (1, 1, 1, 1, 1, 1)
    assert candidate_bucket_limits(0, application_limit=10) == ()


def test_page_count_uses_observed_dice_page_size() -> None:
    assert main_script._bounded_page_count(201, 34, max_pages=None) == 6
    assert main_script._bounded_page_count(201, 34, max_pages=2) == 2
    assert main_script._bounded_page_count(40, 0, max_pages=None) == 2


def test_job_description_supports_current_dice_css_module_markup() -> None:
    selector = '[class*="job-detail-description-module"][class*="jobDescription"]'
    expected = "Build Azure data pipelines with Databricks, Spark, and Python. " * 3
    driver = DescriptionDriver({selector: [DescriptionElement(text=expected)]})

    description = main_script._extract_job_description(driver)

    assert description == expected.strip()


def test_job_description_falls_back_to_canonical_jobposting_structured_data() -> None:
    raw = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "url": "https://www.dice.com/job-detail/current-job",
            "description": (
                "<p>Design reliable <strong>Azure</strong> data pipelines.</p>"
                "<ul><li>Use Databricks and Spark.</li>"
                "<li>Partner with analytics teams.</li></ul>"
                "<p>Automate testing, observability, and production support.</p>"
            ),
        }
    )
    driver = DescriptionDriver(
        {
            'script[data-testid="jobDetailStructuredData"]': [
                DescriptionElement(attributes={"textContent": raw})
            ]
        }
    )

    description = main_script._extract_job_description(driver)

    assert "Design reliable Azure data pipelines." in description
    assert "Use Databricks and Spark." in description
    assert "Partner with analytics teams." in description
    assert "<strong>" not in description


def test_structured_job_description_accepts_jobposting_in_graph_and_ignores_scripts() -> None:
    raw = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "Organization", "description": "not the job"},
                {
                    "@type": ["Thing", "JobPosting"],
                    "url": "https://www.dice.com/job-detail/current-job",
                    "description": (
                        "<style>malicious style text " + "x" * 120 + "</style>"
                        "<script>malicious script text " + "y" * 120 + "</script>"
                        "<p>Develop secure data services and production-grade pipelines "
                        "using Python, SQL, and cloud infrastructure.</p>"
                    ),
                },
            ],
        }
    )
    driver = DescriptionDriver(
        {'script[type="application/ld+json"]': [DescriptionElement(attributes={"innerHTML": raw})]}
    )

    description = main_script._extract_structured_job_description(driver)

    assert description.startswith("Develop secure data services")
    assert "malicious" not in description


def test_structured_job_description_rejects_metadata_for_a_different_job() -> None:
    raw = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "url": "https://www.dice.com/job-detail/different-job",
            "description": "Plausible but wrong job description. " * 20,
        }
    )
    driver = DescriptionDriver(
        {
            'script[data-testid="jobDetailStructuredData"]': [
                DescriptionElement(attributes={"textContent": raw})
            ]
        },
        current_url="https://www.dice.com/job-detail/intended-job?searchlink=search",
    )

    assert main_script._extract_structured_job_description(driver) == ""


def test_structured_job_description_fails_closed_on_wrong_type_or_malformed_json() -> None:
    driver = DescriptionDriver(
        {
            'script[data-testid="jobDetailStructuredData"]': [
                DescriptionElement(
                    attributes={
                        "textContent": json.dumps(
                            {
                                "@type": "Organization",
                                "description": "plausible but untrusted text " * 20,
                            }
                        )
                    }
                ),
                DescriptionElement(attributes={"textContent": "{not valid json"}),
            ]
        }
    )

    assert main_script._extract_structured_job_description(driver) == ""


def test_job_fetch_stops_after_first_empty_results_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    driver = SearchDriver(first_page_size=34)
    monkeypatch.setattr(main_script, "WebDriverWait", ImmediateWait)
    monkeypatch.setattr(main_script.time, "sleep", lambda seconds: None)

    jobs, excluded = fetch_jobs_with_requests(driver, "Data Engineer")

    assert len(jobs) == 34
    assert excluded == []
    assert any("page=2" in url for url in driver.visited)
    assert not any("page=3" in url for url in driver.visited)


def test_candidate_cap_selects_highest_full_description_scores_stably(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    driver = FakeDriver()
    descriptions = {
        "https://www.dice.com/job-detail/low": "low description " * 20,
        "https://www.dice.com/job-detail/high-first": "first high description " * 20,
        "https://www.dice.com/job-detail/high-second": "second high description " * 20,
    }
    monkeypatch.setattr(
        main_script,
        "_extract_job_description",
        lambda current: descriptions[current.current_url],
    )
    service = RankingService(
        evaluations={
            "Low": ranking_evaluation(45),
            "High First": ranking_evaluation(91),
            "High Second": ranking_evaluation(91),
        },
        postings=[],
    )
    jobs = [
        {"Job Title": "Low", "Job URL": "https://www.dice.com/job-detail/low"},
        {
            "Job Title": "High First",
            "Job URL": "https://www.dice.com/job-detail/high-first",
        },
        {
            "Job Title": "High Second",
            "Job URL": "https://www.dice.com/job-detail/high-second",
        },
    ]

    result = rank_eligible_jobs(driver, jobs, service, limit=2)  # type: ignore[arg-type]

    assert [job["Job Title"] for job in result.selected_jobs] == [
        "High First",
        "High Second",
    ]
    assert [job["Job Title"] for job in result.deferred_jobs] == ["Low"]
    assert [posting.description for posting in service.postings] == [
        descriptions[job["Job URL"]] for job in jobs
    ]
    assert all("Job Description" not in job for job in jobs)
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


def test_candidate_ranking_rejects_a_redirected_job_before_evaluation() -> None:
    driver = RedirectingJobDriver()
    service = RankingService(
        evaluations={"Intended": ranking_evaluation(99)},
        postings=[],
    )
    job = {
        "Job Title": "Intended",
        "Job URL": "https://www.dice.com/job-detail/intended-job",
    }

    result = rank_eligible_jobs(driver, [job], service, limit=1)  # type: ignore[arg-type]

    assert result.selected_jobs == ()
    assert result.rejected_jobs == (job,)
    assert "different job detail" in job["Application Reason"]
    assert service.postings == []
    assert driver.current_url == "https://www.dice.com/jobs?q=data"


def test_candidate_ranking_rejects_ineligible_and_manual_review_jobs(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    driver = FakeDriver()
    monkeypatch.setattr(main_script, "_extract_job_description", lambda current: "AWS " * 50)
    service = RankingService(
        evaluations={
            "Safe": ranking_evaluation(70),
            "Below Threshold": ranking_evaluation(20, eligible=False),
            "Clearance": ranking_evaluation(
                95,
                manual_review_reasons=("clearance requirement",),
            ),
        },
        postings=[],
    )
    jobs = [
        {"Job Title": title, "Job URL": f"https://www.dice.com/job-detail/{index}"}
        for index, title in enumerate(("Below Threshold", "Clearance", "Safe"), start=1)
    ]

    result = rank_eligible_jobs(driver, jobs, service, limit=3)  # type: ignore[arg-type]

    assert [job["Job Title"] for job in result.selected_jobs] == ["Safe"]
    assert {job["Job Title"] for job in result.rejected_jobs} == {
        "Below Threshold",
        "Clearance",
    }
    assert all(
        job["Application Status"] == ApplicationStatus.SKIPPED.value for job in result.rejected_jobs
    )
