from core.dice_login import _profile_page_confirms_authenticated_session


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


def test_login_form_on_profile_route_does_not_confirm_login() -> None:
    assert not _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "Welcome Log in to continue",
        login_form_visible=True,
        account_control_visible=False,
    )


def test_account_control_confirms_loaded_profile_page() -> None:
    assert _profile_page_confirms_authenticated_session(
        "https://www.dice.com/dashboard/profiles",
        "My profile",
        login_form_visible=False,
        account_control_visible=True,
    )
