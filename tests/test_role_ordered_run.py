from __future__ import annotations

import json
from pathlib import Path

from core.main_script import ApplicationStatus
from scripts.run_role_ordered import _append_ledger, _recorded_applied_urls


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
