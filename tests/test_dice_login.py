import core.main_script as main_script
from core.dice_login import (
    _profile_page_confirms_authenticated_session,
    get_headless_driver,
)


class FakeDriver:
    def __init__(self) -> None:
        self.page_load_timeout = None

    def set_page_load_timeout(self, timeout: int) -> None:
        self.page_load_timeout = timeout


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
