from __future__ import annotations

import json
from pathlib import Path

import scripts.run_role_ordered as role_ordered
from core.main_script import ApplicationResult, ApplicationStatus
from scripts.run_role_ordered import _append_ledger, _browser_session_lost, _recorded_applied_urls


def test_ledger_recovers_only_dice_confirmed_submission_urls(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _append_ledger(
        ledger, {"status": ApplicationStatus.APPLIED.value, "job_url": "https://dice.com/a"}
    )
    _append_ledger(
        ledger,
        {"status": ApplicationStatus.ALREADY_APPLIED.value, "job_url": "https://dice.com/existing"},
    )
    _append_ledger(
        ledger, {"status": ApplicationStatus.SKIPPED.value, "job_url": "https://dice.com/b"}
    )
    ledger.write_text(ledger.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")

    assert _recorded_applied_urls(ledger) == {"https://dice.com/a", "https://dice.com/existing"}
    assert json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["status"] == "applied"


def test_browser_session_recovery_is_limited_to_closed_browser_failures() -> None:
    assert _browser_session_lost("Application flow failed: NoSuchWindowException.")
    assert _browser_session_lost("target window already closed from unknown error")
    assert not _browser_session_lost("Dice did not confirm the application.")


def test_role_run_restarts_browser_and_continues_with_next_result(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    class Driver:
        def __init__(self) -> None:
            self.quit_called = False

        def quit(self) -> None:
            self.quit_called = True

    created_drivers = [Driver(), Driver()]
    drivers = list(created_drivers)
    applied_urls: list[str] = []
    events: list[dict[str, str]] = []

    monkeypatch.setenv("DICE_USERNAME", "candidate@example.com")
    monkeypatch.setenv("DICE_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(role_ordered, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        role_ordered,
        "_load_settings",
        lambda: {
            "search_queries": ["Data Engineer"],
            "include_keywords": [],
            "exclude_keywords": [],
        },
    )
    monkeypatch.setattr(
        role_ordered.ResumeService,
        "from_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(role_ordered, "get_web_driver", lambda **kwargs: drivers.pop(0))
    monkeypatch.setattr(role_ordered, "authenticate_dice_session", lambda *args: (True, ""))
    monkeypatch.setattr(
        role_ordered,
        "fetch_jobs_with_requests",
        lambda *args, **kwargs: (
            [
                {"Job Title": "First", "Job URL": "https://www.dice.com/job-detail/first"},
                {"Job Title": "Second", "Job URL": "https://www.dice.com/job-detail/second"},
            ],
            [],
        ),
    )

    def apply(_driver, job, _service, **_kwargs):
        applied_urls.append(job["Job URL"])
        if len(applied_urls) == 1:
            return ApplicationResult(
                ApplicationStatus.FAILED,
                "Application flow failed: NoSuchWindowException.",
            )
        return ApplicationResult(ApplicationStatus.APPLIED, "Dice confirmed submission.")

    monkeypatch.setattr(role_ordered, "apply_to_job_url", apply)

    submitted = role_ordered.run(
        1,
        skip_review=True,
        ledger_path=tmp_path / "ledger.jsonl",
        event_callback=events.append,
    )

    assert submitted == 1
    assert applied_urls == [
        "https://www.dice.com/job-detail/first",
        "https://www.dice.com/job-detail/second",
    ]
    assert all(driver.quit_called for driver in created_drivers)
    assert any(event.get("stage") == "recovering_browser" for event in events)


def test_role_run_finishes_current_results_page_before_loading_next_page(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    class Driver:
        def quit(self) -> None:
            pass

    sequence: list[str] = []
    monkeypatch.setenv("DICE_USERNAME", "candidate@example.com")
    monkeypatch.setenv("DICE_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(role_ordered, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        role_ordered,
        "_load_settings",
        lambda: {
            "search_queries": list(role_ordered.ROLE_SEARCH_ORDER),
            "include_keywords": [],
            "exclude_keywords": [],
        },
    )
    monkeypatch.setattr(
        role_ordered.ResumeService,
        "from_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(role_ordered, "get_web_driver", lambda **kwargs: Driver())
    monkeypatch.setattr(role_ordered, "authenticate_dice_session", lambda *args: (True, ""))

    def fetch(_driver, query, *_args, **kwargs):
        page = kwargs["start_page"]
        sequence.append(f"fetch:{query}:{page}")
        if query != "Data Engineer":
            return ([], [])
        return (
            [
                {
                    "Job Title": f"Page {page}",
                    "Job URL": f"https://www.dice.com/job-detail/page-{page}",
                }
            ],
            [],
        )

    def apply(_driver, job, _service, **_kwargs):
        sequence.append(f"apply:{job['Job Title']}")
        if job["Job Title"] == "Page 1":
            return ApplicationResult(ApplicationStatus.SKIPPED, "No Easy Apply")
        return ApplicationResult(ApplicationStatus.APPLIED, "Dice confirmed submission.")

    monkeypatch.setattr(role_ordered, "fetch_jobs_with_requests", fetch)
    monkeypatch.setattr(role_ordered, "apply_to_job_url", apply)

    assert role_ordered.run(1, skip_review=True, ledger_path=tmp_path / "ledger.jsonl") == 1
    assert sequence[:4] == [
        "fetch:Data Engineer:1",
        "apply:Page 1",
        "fetch:Data Engineer:2",
        "apply:Page 2",
    ]


def test_role_run_uses_fixed_role_and_result_order(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    class Driver:
        def quit(self) -> None:
            pass

    sequence: list[str] = []
    monkeypatch.setenv("DICE_USERNAME", "candidate@example.com")
    monkeypatch.setenv("DICE_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(role_ordered, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        role_ordered,
        "_load_settings",
        lambda: {
            # Live submission must not inherit an accidentally reordered UI value.
            "search_queries": list(reversed(role_ordered.ROLE_SEARCH_ORDER)),
            "include_keywords": [],
            "exclude_keywords": [],
        },
    )
    monkeypatch.setattr(
        role_ordered.ResumeService,
        "from_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(role_ordered, "get_web_driver", lambda **kwargs: Driver())
    monkeypatch.setattr(role_ordered, "authenticate_dice_session", lambda *args: (True, ""))

    def fetch(_driver, query, *_args, **kwargs):
        sequence.append(f"search:{query}")
        return (
            [
                {
                    "Job Title": f"{query} result {position}",
                    "Job URL": f"https://www.dice.com/job-detail/{query}-{position}",
                }
                for position in (1, 2)
            ],
            [],
        )

    def apply(_driver, job, _service, **_kwargs):
        sequence.append(f"apply:{job['Job Title']}")
        return ApplicationResult(ApplicationStatus.APPLIED, "Dice confirmed submission.")

    monkeypatch.setattr(role_ordered, "fetch_jobs_with_requests", fetch)
    monkeypatch.setattr(role_ordered, "apply_to_job_url", apply)

    submitted = role_ordered.run(
        2,
        skip_review=True,
        ledger_path=tmp_path / "ledger.jsonl",
    )

    assert submitted == 2 * len(role_ordered.ROLE_SEARCH_ORDER)
    assert sequence == [
        event
        for query in role_ordered.ROLE_SEARCH_ORDER
        for event in (
            f"search:{query}",
            f"apply:{query} result 1",
            f"apply:{query} result 2",
        )
    ]
