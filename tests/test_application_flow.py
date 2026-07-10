from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import core.main_script as main_script
from core.authorization import DiceAuthorizationError
from core.main_script import (
    ApplicationStatus,
    RunMode,
    apply_to_job_url,
    fetch_jobs_with_requests,
)
from core.resumes.models import (
    CloudProfile,
    MatchDecision,
    PreparedResume,
    ResumePreparation,
)


class FakeDriver:
    def __init__(self) -> None:
        self.current_url = "https://www.dice.com/jobs?q=data"
        self.visited: list[str] = []

    def get(self, url: str) -> None:
        self.current_url = url
        self.visited.append(url)


class FakeElement:
    def __init__(
        self,
        text: str = "",
        href: str = "",
        *,
        enabled: bool = True,
        displayed: bool = True,
        accepts_file: bool = True,
    ) -> None:
        self.text = text
        self.href = href
        self.enabled = enabled
        self.displayed = displayed
        self.accepts_file = accepts_file
        self.clicked = False
        self.value = ""
        self.selected_file_name = ""

    def is_displayed(self) -> bool:
        return self.displayed

    def is_enabled(self) -> bool:
        return self.enabled

    def get_attribute(self, name: str) -> str:
        if name == "href":
            return self.href
        if name == "value":
            return self.value
        return ""

    def click(self) -> None:
        self.clicked = True

    def send_keys(self, value: str) -> None:
        if self.accepts_file:
            self.value = value
            self.selected_file_name = Path(value).name


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
    ) -> None:
        super().__init__()
        self.apply_control = FakeElement(apply_text, enabled=apply_enabled)
        self.submit_button = FakeElement("Submit")
        self.next_button = FakeElement("Next") if has_next else None
        self.file_input = FakeElement(accepts_file=accepts_file) if has_file_input else None
        self.screening_control = FakeElement() if has_screening_control else None
        self.confirmation = FakeElement("Application submitted") if confirmed else None
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
    assert "could not be uploaded" in result.reason
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
