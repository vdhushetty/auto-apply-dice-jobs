from selenium.webdriver.common.by import By

import core.dice_login as dice_login
import core.main_script as main_script
from core.dice_login import (
    _profile_page_confirms_authenticated_session,
    authenticate_dice_session,
    get_headless_driver,
    restore_dice_session,
)


class FakeDriver:
    def __init__(self) -> None:
        self.page_load_timeout = None

    def set_page_load_timeout(self, timeout: int) -> None:
        self.page_load_timeout = timeout


class VisibleElement:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def is_displayed(self) -> bool:
        return True


class AuthenticatedSessionDriver:
    def __init__(self) -> None:
        self.current_url = ""
        self.added_cookies: list[dict[str, object]] = []

    def get(self, url: str) -> None:
        self.current_url = url

    def delete_all_cookies(self) -> None:
        return None

    def add_cookie(self, cookie: dict[str, object]) -> None:
        self.added_cookies.append(cookie)

    def find_elements(self, by: str, selector: str) -> list[VisibleElement]:
        if by == By.TAG_NAME and selector == "body":
            return [VisibleElement("Profile information Complete your experience")]
        return []

    def execute_script(self, script: str) -> str:
        assert script == "return document.readyState"
        return "complete"


def test_headless_driver_uses_browser_factory_with_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    driver = FakeDriver()
    requested_modes: list[bool] = []

    def fake_get_web_driver(headless: bool = False):  # type: ignore[no-untyped-def]
        requested_modes.append(headless)
        return driver

    monkeypatch.setattr(main_script, "get_web_driver", fake_get_web_driver)

    assert get_headless_driver() is driver
    assert requested_modes == [True]
    assert driver.page_load_timeout == 25


def test_public_search_page_does_not_confirm_login() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/jobs",
        "Search thousands of technology jobs",
        login_form_visible=False,
        account_control_visible=False,
    )


def test_protected_profile_account_content_confirms_login() -> None:
    assert _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "My profile Profile visibility Upload resume",
        login_form_visible=False,
        account_control_visible=False,
    )


def test_loaded_protected_profile_with_changed_copy_confirms_login() -> None:
    assert _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "Career profile Complete your experience",
        login_form_visible=False,
        account_control_visible=False,
        page_ready=True,
    )


def test_current_profile_info_route_confirms_login() -> None:
    assert _profile_page_confirms_authenticated_session(
        "https://www.dice.com/profile/info",
        "Profile information Complete your experience",
        login_form_visible=False,
        account_control_visible=False,
        page_ready=True,
    )


def test_login_form_on_profile_route_does_not_confirm_login() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "Welcome Log in to continue",
        login_form_visible=True,
        account_control_visible=False,
    )


def test_generic_sign_in_copy_on_preserved_profile_route_does_not_confirm_login() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/profile/info",
        "Sign in to access your account",
        login_form_visible=False,
        account_control_visible=False,
        page_ready=True,
    )


def test_login_redirect_query_does_not_look_like_protected_profile() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/login?redirectUrl=/dashboard/profiles",
        "Create an account or sign in",
        login_form_visible=False,
        account_control_visible=False,
    )


def test_profile_404_does_not_confirm_login() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "Oops! It looks like this page doesn't exist.",
        login_form_visible=False,
        account_control_visible=False,
    )


def test_profile_must_finish_loading_before_confirmation() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "Career profile",
        login_form_visible=False,
        account_control_visible=False,
        page_ready=False,
    )


def test_account_control_confirms_loaded_profile_page() -> None:
    assert _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "My profile",
        login_form_visible=False,
        account_control_visible=True,
    )


def test_restore_session_transfers_only_dice_domain_cookies() -> None:
    driver = AuthenticatedSessionDriver()

    assert restore_dice_session(
        driver,
        (
            {"name": "session", "value": "opaque", "domain": ".dice.com", "path": "/"},
            {"name": "nested", "value": "opaque-2", "domain": "www.dice.com"},
            {"name": "foreign", "value": "do-not-copy", "domain": ".example.com"},
        ),
        timeout=0,
    )

    assert [cookie["name"] for cookie in driver.added_cookies] == ["session", "nested"]
    assert driver.current_url == dice_login.ACCOUNT_PROFILE_URL


def test_authenticate_reuses_verified_session_without_credential_login(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    statuses: list[str] = []
    monkeypatch.setattr(dice_login, "restore_dice_session", lambda driver, cookies: True)

    def unexpected_login(driver, credentials):  # type: ignore[no-untyped-def]
        raise AssertionError("credential login must not run after successful session reuse")

    monkeypatch.setattr(dice_login, "login_to_dice", unexpected_login)

    assert authenticate_dice_session(
        object(),
        ("person@example.com", "top-secret"),
        session_cookies=({"name": "session", "value": "opaque", "domain": ".dice.com"},),
        status_callback=statuses.append,
    ) == (True, True)
    assert statuses == [
        "Restoring verified Dice session...",
        "Verified Dice session restored. Fetching jobs...",
    ]


def test_expired_session_falls_back_to_normal_login_without_exposing_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    username = "secret-user@example.com"
    password = "never-log-this-password"
    statuses: list[str] = []
    received_credentials: list[tuple[str, str]] = []
    monkeypatch.setattr(dice_login, "restore_dice_session", lambda driver, cookies: False)

    def successful_login(driver, credentials):  # type: ignore[no-untyped-def]
        received_credentials.append(credentials)
        return True

    monkeypatch.setattr(dice_login, "login_to_dice", successful_login)

    assert authenticate_dice_session(
        object(),
        (username, password),
        session_cookies=({"name": "expired", "value": "cookie-secret"},),
        status_callback=statuses.append,
    ) == (True, False)
    assert received_credentials == [(username, password)]
    rendered_status = " ".join(statuses)
    assert username not in rendered_status
    assert password not in rendered_status
    assert "cookie-secret" not in rendered_status
    assert statuses == [
        "Restoring verified Dice session...",
        "Verified Dice session expired; signing in again...",
        "Login successful. Fetching jobs...",
    ]
