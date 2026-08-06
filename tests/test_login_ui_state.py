from __future__ import annotations

from types import SimpleNamespace

from app_tkinter import DiceAutoBotApp, _credential_fingerprint
from core.main_script import ApplicationStatus, RunMode


class DummyEntry:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class DummyWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def config(self, **options: object) -> None:
        self.options.update(options)


class DummyLogger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


class AliveThread:
    def is_alive(self) -> bool:
        return True


class DummyNotebook:
    def __init__(self) -> None:
        self.selected = None

    def select(self, index: int) -> None:
        self.selected = index


def build_login_state_app() -> DiceAutoBotApp:
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    app.username_entry = DummyEntry("person@example.com")
    app.password_entry = DummyEntry("correct horse battery staple")
    app.test_login_button = DummyWidget()
    app.login_status_label = DummyWidget()
    app.verified_credentials_fingerprint = None
    app.login_session_cookies = ()
    return app


def test_verified_login_has_persistent_status_separate_from_action_button() -> None:
    app = build_login_state_app()
    fingerprint = _credential_fingerprint(
        app.username_entry.get(),
        app.password_entry.get(),
    )

    remembered = app._remember_verified_login(
        fingerprint,
        ({"name": "session", "value": "opaque", "domain": ".dice.com"},),
    )

    assert remembered
    assert app.test_login_button.options["text"] == "Test Again"
    assert "verified" in str(app.login_status_label.options["text"]).lower()
    assert app.verified_credentials_fingerprint == fingerprint


def test_editing_credentials_clears_verified_session() -> None:
    app = build_login_state_app()
    fingerprint = _credential_fingerprint(
        app.username_entry.get(),
        app.password_entry.get(),
    )
    app._remember_verified_login(
        fingerprint,
        ({"name": "session", "value": "opaque", "domain": ".dice.com"},),
    )

    app.password_entry.value = "a new password"
    app.on_credentials_changed()

    assert app.verified_credentials_fingerprint is None
    assert app.login_session_cookies == ()
    assert app.test_login_button.options["text"] == "Test Login"
    assert "changed" in str(app.login_status_label.options["text"]).lower()


def test_start_waits_for_login_test_to_finish(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    app.login_test_thread = AliveThread()
    app.notebook = DummyNotebook()
    messages = []
    monkeypatch.setattr(
        "app_tkinter.messagebox.showinfo",
        lambda title, message: messages.append((title, message)),
    )

    app.start_applying()

    assert messages == [
        (
            "Login Test Running",
            "Wait for Test Login to finish and show the verified status before starting.",
        )
    ]
    assert app.notebook.selected == 1


def test_login_state_never_keeps_non_dice_cookies() -> None:
    app = build_login_state_app()
    fingerprint = _credential_fingerprint(
        app.username_entry.get(),
        app.password_entry.get(),
    )

    app._remember_verified_login(
        fingerprint,
        ({"name": "foreign", "value": "secret", "domain": ".example.com"},),
    )

    assert app.login_session_cookies == ()
    assert "credentials verified" in str(app.login_status_label.options["text"]).lower()


def test_submit_start_delegates_to_role_ordered_runner() -> None:
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    received = []
    app._run_role_ordered_submission = lambda limit, mode, policy: received.append(
        (limit, mode, policy)
    )
    app.selected_ai_review_policy = lambda: "skip_review"
    service = SimpleNamespace(mode=SimpleNamespace(value="ai_bullets"))

    app.run_job_application([], [], [], "", "", service, False, 10, RunMode.SUBMIT, "", ())

    assert received == [(10, "ai_bullets", "skip_review")]


def test_role_ordered_runner_surfaces_confirmed_submission(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = DiceAutoBotApp.__new__(DiceAutoBotApp)
    statuses: list[str] = []
    notices = []
    app.running = True
    app.logger = DummyLogger()
    app.jobs_applied_label = DummyWidget()
    app.jobs_skipped_label = DummyWidget()
    app.jobs_failed_label = DummyWidget()
    app.update_status = statuses.append
    app.post_ui = lambda callback: callback()
    app.reset_ui = lambda: statuses.append("reset")
    monkeypatch.setattr(
        "app_tkinter.run_role_ordered",
        lambda limit, **kwargs: (
            kwargs["event_callback"](
                {
                    "status": ApplicationStatus.APPLIED.value,
                    "job_title": "Data Engineer",
                }
            )
            or 1
        ),
    )
    monkeypatch.setattr(
        "app_tkinter.messagebox.showinfo",
        lambda title, message: notices.append((title, message)),
    )

    app._run_role_ordered_submission(10, "ai_bullets", "skip_review")

    assert app.jobs_applied_label.options["text"] == "1"
    assert any("Dice confirmed 1 new application" in value for value in statuses)
    assert notices and notices[0][0] == "Process Complete"
    assert statuses[-1] == "reset"
