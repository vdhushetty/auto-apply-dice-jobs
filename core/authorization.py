"""Central authorization guard for live Dice browser automation."""

from __future__ import annotations

import os


class DiceAuthorizationError(PermissionError):
    """Raised when live Dice automation has not been explicitly authorized."""


def require_dice_automation_authorized() -> None:
    """Fail closed unless prior Dice authorization is explicitly attested."""

    authorized = os.getenv("DICE_AUTOMATION_AUTHORIZED", "").strip().lower()
    if authorized != "true":
        raise DiceAuthorizationError(
            "Live Dice automation is disabled. Set DICE_AUTOMATION_AUTHORIZED=true "
            "only after obtaining Dice's prior written authorization."
        )
