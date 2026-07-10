import pytest

import core.dice_login as dice_login
from core.authorization import DiceAuthorizationError, require_dice_automation_authorized


def test_authorization_guard_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DICE_AUTOMATION_AUTHORIZED", raising=False)

    with pytest.raises(DiceAuthorizationError):
        require_dice_automation_authorized()


def test_login_validation_checks_authorization_before_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DICE_AUTOMATION_AUTHORIZED", raising=False)
    monkeypatch.setattr(
        dice_login,
        "get_headless_driver",
        lambda: (_ for _ in ()).throw(AssertionError("browser must not start")),
    )

    with pytest.raises(DiceAuthorizationError):
        dice_login.validate_dice_credentials("example", "example")
