from __future__ import annotations

import queue

from app_tkinter import DiceAutoBotApp, _discovered_prior_applications


class _ImmediateRoot:
    def after(self, _delay, callback):  # type: ignore[no-untyped-def]
        callback()


class _Label:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def config(self, *, text: str) -> None:
        self.text = text


class _Logger:
    def info(self, _message: str) -> None:
        pass


def test_prior_application_count_uses_only_jobs_discovered_in_this_run() -> None:
    discovered = {
        "https://www.dice.com/job-detail/current": {"Job Title": "Current"},
        "https://www.dice.com/job-detail/new": {"Job Title": "New"},
    }
    historical_urls = {
        "https://www.dice.com/job-detail/current",
        "https://www.dice.com/job-detail/old-ledger-only",
    }

    matches = _discovered_prior_applications(discovered, historical_urls)

    assert matches == [{"Job Title": "Current"}]


def test_stop_summary_does_not_replace_discovered_job_count() -> None:
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    app.root = _ImmediateRoot()
    app.post_ui = lambda callback: callback()
    app.logger = _Logger()
    app.status_label = _Label()
    app.current_step_label = _Label()
    app.last_result_label = _Label()
    app.jobs_found_label = _Label("42")
    app.jobs_applied_label = _Label()
    app.jobs_ready_label = _Label()
    app.jobs_already_applied_label = _Label()
    app.jobs_skipped_label = _Label()
    app.jobs_failed_label = _Label()

    app.show_stop_summary(
        "Stopped by user",
        processed=1,
        total=3,
        applied=0,
        ready=0,
        already_applied=0,
        skipped=1,
        failed=0,
    )

    assert app.jobs_found_label.text == "42"
    assert "Processed 1/3" in app.status_label.text


def test_worker_status_update_is_queued_before_touching_tk_widgets() -> None:
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    app._ui_callbacks = queue.SimpleQueue()
    app.logger = _Logger()
    app.status_label = _Label()

    app.update_status("Worker update")

    assert app.status_label.text == ""
    app._ui_callbacks.get_nowait()()
    assert app.status_label.text == "Worker update"
