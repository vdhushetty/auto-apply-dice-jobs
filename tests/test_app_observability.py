from __future__ import annotations

from app_tkinter import (
    _application_progress_view,
    _preflight_rejection_counts,
    _ranked_jobs_for_run,
    _run_completion_summary,
    _run_stop_summary,
    _safe_ui_message,
)
from core.main_script import (
    ApplicationProgress,
    ApplicationProgressStage,
    JobSelection,
    RunMode,
)


def test_progress_view_surfaces_job_step_generated_resume_and_result() -> None:
    event = ApplicationProgress(
        stage=ApplicationProgressStage.COMPLETED,
        message="Dice confirmed the application submission.",
        job_title="Data Engineer",
        status="applied",
        resume_profile="aws",
        resume_filename="generated.docx",
        resume_kind="generated",
    )

    job, step, resume, result = _application_progress_view(event, 2, 5)

    assert job == "2/5 — Data Engineer"
    assert step.startswith("Completed:")
    assert resume == "Generated — AWS — generated.docx"
    assert result == "Applied: Dice confirmed the application submission."


def test_status_sanitizer_hides_secret_like_tokens_and_local_paths() -> None:
    value = "OpenAI sk-proj-1234567890 failed at /Users/person/private/resume.docx"

    sanitized = _safe_ui_message(value)

    assert "sk-proj" not in sanitized
    assert "/Users/" not in sanitized
    assert "[redacted token]" in sanitized
    assert "[local path]" in sanitized


def test_stop_summary_includes_reason_and_all_counts() -> None:
    summary = _run_stop_summary(
        "Stopped by user",
        processed=3,
        total=10,
        applied=1,
        ready=1,
        already_applied=0,
        skipped=1,
        failed=0,
    )

    assert summary == (
        "Stopped: Stopped by user. Processed 3/10; Applied: 1, Ready/verified: 1, "
        "Already applied: 0, Skipped: 1, Failed: 0."
    )


def test_no_upload_completion_persists_preflight_count_and_top_reason() -> None:
    summary = _run_completion_summary(
        selected_jobs=0,
        applied=0,
        ready=0,
        already_applied=0,
        skipped=6,
        failed=0,
        elapsed="0h 0m 4.00s",
        top_preflight_reason="Dice job description could not be read.",
    )

    assert summary == (
        "No eligible job reached upload. Top reason: Dice job description could not be read. "
        "Applied: 0, Ready/verified: 0, Already applied: 0, Skipped: 6, Failed: 0, "
        "Time: 0h 0m 4.00s"
    )


def test_verify_completion_explains_when_ranked_candidates_never_upload() -> None:
    summary = _run_completion_summary(
        selected_jobs=2,
        applied=0,
        ready=0,
        already_applied=1,
        skipped=1,
        failed=0,
        elapsed="0h 0m 8.00s",
        verify_upload=True,
        last_attempt_reason="Only Dice Easy Apply is supported.",
    )

    assert summary.startswith(
        "No upload was verified. Last reason: Only Dice Easy Apply is supported."
    )


def test_verify_mode_opens_only_the_highest_ranked_selected_job() -> None:
    first = {"Job Title": "First"}
    second = {"Job Title": "Second"}
    deferred = {"Job Title": "Deferred"}
    selection = JobSelection(
        selected_jobs=(first, second),
        deferred_jobs=(deferred,),
        rejected_jobs=(),
        assessed_count=3,
    )

    assert _ranked_jobs_for_run(selection, RunMode.VERIFY_UPLOAD) == [first]
    assert first["Selection Status"] == "verify_candidate"
    assert "Selection Status" not in second
    assert "Selection Status" not in deferred
    assert _ranked_jobs_for_run(selection, RunMode.SUBMIT) == [first, second]


def test_preflight_rejections_are_grouped_and_counted_as_skips() -> None:
    counts = _preflight_rejection_counts(
        [
            {"Application Reason": "Description unreadable"},
            {"Application Reason": "Below resume threshold"},
            {"Application Reason": "Description unreadable"},
        ]
    )

    assert counts == {
        "Description unreadable": 2,
        "Below resume threshold": 1,
    }
    assert sum(counts.values()) == 3
