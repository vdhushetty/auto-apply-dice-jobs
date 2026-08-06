from __future__ import annotations

import json
from pathlib import Path

from core.application_dashboard import (
    dashboard_skip_reason_counts,
    dashboard_status_counts,
    load_application_dashboard,
)


def test_dashboard_joins_applied_job_to_manifested_bullet_changes(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    resume = resume_dir / "data-engineer.docx"
    resume.touch()
    (resume_dir / "data-engineer.docx.manifest.json").write_text(
        json.dumps(
            {
                "validated_plan": {
                    "edits": [
                        {
                            "bullet_id": "bullet-0043",
                            "replacement_bullets": ["Built governed Databricks data pipelines."],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "completed_at": "2026-08-06T00:00:00Z",
                        "query": "Data Engineer",
                        "job_title": "Data Engineer",
                        "job_url": "https://www.dice.com/job-detail/example",
                        "status": "applied",
                        "reason": "Dice confirmed the application submission.",
                        "resume_filename": "data-engineer.docx",
                    }
                ),
                json.dumps(
                    {
                        "query": "Data Engineer",
                        "job_title": "Onsite job",
                        "status": "skipped",
                        "reason": "Manual review required before applying: onsite requirement.",
                        "resume_filename": "",
                    }
                ),
                "not-json",
            )
        ),
        encoding="utf-8",
    )

    records = load_application_dashboard(ledger, resume_dir)

    assert [record.status for record in records] == ["skipped", "applied"]
    applied = records[1]
    assert applied.resume_path == resume
    assert applied.changes[0].bullet_id == "bullet-0043"
    assert applied.changes[0].replacement_bullets == ("Built governed Databricks data pipelines.",)
    assert dashboard_status_counts(records) == {"skipped": 1, "applied": 1}
    assert dashboard_skip_reason_counts(records) == {
        "Manual review required before applying: onsite requirement.": 1
    }
