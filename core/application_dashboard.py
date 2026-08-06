"""Durable, local-only records for the desktop application dashboard."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResumeBulletChange:
    """A validated generated resume bullet replacement safe to display to the owner."""

    bullet_id: str
    replacement_bullets: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationDashboardRecord:
    completed_at: str
    query: str
    job_title: str
    job_url: str
    status: str
    reason: str
    resume_filename: str
    resume_path: Path | None
    changes: tuple[ResumeBulletChange, ...]


def _read_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            records.append(entry)
    return records


def _manifest_changes(manifest_path: Path) -> tuple[ResumeBulletChange, ...]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plan = manifest.get("validated_plan", {})
        edits = plan.get("edits", []) if isinstance(plan, dict) else []
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(edits, list):
        return ()
    changes: list[ResumeBulletChange] = []
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        bullet_id = str(edit.get("bullet_id", "")).strip()
        replacements = edit.get("replacement_bullets", [])
        if not bullet_id or not isinstance(replacements, list):
            continue
        normalized = tuple(str(item).strip() for item in replacements if str(item).strip())
        if normalized:
            changes.append(ResumeBulletChange(bullet_id, normalized))
    return tuple(changes)


def load_application_dashboard(
    ledger_path: str | Path,
    resume_directory: str | Path,
) -> tuple[ApplicationDashboardRecord, ...]:
    """Join durable job outcomes with the matching local resume manifest, if present."""

    ledger = Path(ledger_path)
    resume_dir = Path(resume_directory)
    records: list[ApplicationDashboardRecord] = []
    for entry in reversed(_read_ledger(ledger)):
        filename = Path(str(entry.get("resume_filename", ""))).name
        resume_path = resume_dir / filename if filename else None
        if resume_path is not None and not resume_path.is_file():
            resume_path = None
        manifest_path = (
            resume_path.with_suffix(resume_path.suffix + ".manifest.json")
            if resume_path is not None
            else None
        )
        records.append(
            ApplicationDashboardRecord(
                completed_at=str(entry.get("completed_at", "")),
                query=str(entry.get("query", "")),
                job_title=str(entry.get("job_title", "Unknown job")),
                job_url=str(entry.get("job_url", "")),
                status=str(entry.get("status", "unknown")),
                reason=str(entry.get("reason", "")),
                resume_filename=filename,
                resume_path=resume_path,
                changes=_manifest_changes(manifest_path) if manifest_path is not None else (),
            )
        )
    return tuple(records)


def dashboard_status_counts(records: tuple[ApplicationDashboardRecord, ...]) -> Counter[str]:
    return Counter(record.status for record in records)


def dashboard_skip_reason_counts(records: tuple[ApplicationDashboardRecord, ...]) -> Counter[str]:
    return Counter(
        record.reason for record in records if record.status == "skipped" and record.reason
    )
