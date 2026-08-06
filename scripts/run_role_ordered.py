"""Run bounded Dice submissions in configured role order with a durable local ledger.

This is a live-only operator command. It requires the repository's existing authorization gate,
the ignored local ``.env`` credentials, and an explicit ``--skip-review`` acknowledgement for
unattended AI bullet tailoring. It records every completed Dice result immediately so a later
run never retries a Dice-confirmed submission from this command's ledger.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.dice_login import authenticate_dice_session
from core.main_script import (
    ApplicationStatus,
    RunMode,
    apply_to_job_url,
    fetch_jobs_with_requests,
    get_web_driver,
)
from core.resumes import ResumeService

LEDGER_PATH = Path(".data/role_ordered_runs/ledger.jsonl")
_CANDIDATE_POOL_MULTIPLIER = 4


def _load_settings() -> dict[str, Any]:
    settings = json.loads(Path("config/settings.json").read_text(encoding="utf-8"))
    local_path = Path("config/settings.local.json")
    if local_path.exists():
        settings.update(json.loads(local_path.read_text(encoding="utf-8")))
    return settings


def _recorded_applied_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    urls: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("status") in {
            ApplicationStatus.APPLIED.value,
            ApplicationStatus.ALREADY_APPLIED.value,
        }:
            url = entry.get("job_url")
            if isinstance(url, str) and url:
                urls.add(url)
    return urls


def _append_ledger(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(dict(entry), ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())
    if os.name != "nt":
        os.chmod(path, 0o600)


def _outcome_entry(query: str, job: Mapping[str, Any], result) -> dict[str, Any]:
    return {
        "completed_at": datetime.now(UTC).isoformat(),
        "query": query,
        "job_title": str(job.get("Job Title", "")),
        "job_url": str(job.get("Job URL", "")),
        "status": result.status.value,
        "reason": result.reason,
        "resume_filename": result.resume_filename,
    }


def run(
    limit: int,
    *,
    skip_review: bool,
    ledger_path: Path = LEDGER_PATH,
    event_callback: Callable[[Mapping[str, Any]], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> int:
    """Apply to at most ``limit`` new jobs for each configured role, in result order."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not skip_review:
        raise ValueError("Unattended live runs require explicit --skip-review.")

    load_dotenv(".env", override=True)
    settings = _load_settings()
    settings["ai_review_policy"] = "skip_review"
    username = os.environ.get("DICE_USERNAME", "").strip()
    password = os.environ.get("DICE_PASSWORD", "").strip()
    if not username or not password:
        raise ValueError("DICE_USERNAME and DICE_PASSWORD are required in .env.")
    service = ResumeService.from_settings(
        settings,
        api_key=os.environ.get("OPENAI_API_KEY"),
        safety_identity=username,
    )
    queries = [
        str(value).strip() for value in settings.get("search_queries", ()) if str(value).strip()
    ]
    if not queries:
        raise ValueError("At least one search query is required.")

    known_applied = _recorded_applied_urls(ledger_path)
    seen_urls = set(known_applied)
    submitted = 0
    driver = get_web_driver(headless=False)
    try:
        authenticated, _ = authenticate_dice_session(driver, (username, password))
        if not authenticated:
            raise RuntimeError("Dice authentication was not confirmed.")
        for query in queries:
            if cancel_requested is not None and cancel_requested():
                break
            role_submitted = 0
            jobs, _ = fetch_jobs_with_requests(
                driver,
                query,
                settings.get("include_keywords"),
                settings.get("exclude_keywords"),
                max_pages=2,
                max_included_jobs=limit * _CANDIDATE_POOL_MULTIPLIER,
            )
            fresh_jobs = []
            for job in jobs:
                url = str(job.get("Job URL", ""))
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    job["Search Query"] = query
                    fresh_jobs.append(job)
            for job in fresh_jobs:
                if cancel_requested is not None and cancel_requested():
                    break
                if role_submitted >= limit:
                    break
                result = apply_to_job_url(
                    driver,
                    job,
                    service,
                    run_mode=RunMode.SUBMIT,
                    cancel_requested=cancel_requested,
                )
                entry = _outcome_entry(query, job, result)
                _append_ledger(ledger_path, entry)
                print(json.dumps(entry, ensure_ascii=False), flush=True)
                if event_callback is not None:
                    event_callback(entry)
                if result.status is ApplicationStatus.APPLIED:
                    submitted += 1
                    role_submitted += 1
    finally:
        driver.quit()
    print(json.dumps({"submitted": submitted, "per_role_cap": limit}), flush=True)
    return submitted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-review", action="store_true")
    args = parser.parse_args()
    settings = _load_settings()
    limit = args.limit if args.limit is not None else int(settings.get("job_application_limit", 10))
    run(limit, skip_review=args.skip_review)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
