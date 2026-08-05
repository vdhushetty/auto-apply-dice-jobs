"""Opt-in live OpenAI smoke tests using local DOCX resumes and synthetic jobs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from core.resumes import JobPosting, ResumeService
from core.resumes.models import CloudProfile, ResumeMode

SYNTHETIC_JOBS = (
    (
        CloudProfile.AWS,
        "AWS Data Engineer",
        "Required: AWS Glue, S3, Redshift, Lake Formation, Python, SQL, and Spark.",
    ),
    (
        CloudProfile.AZURE,
        "Azure Data Engineer",
        "Required: ADLS Gen2, Azure Data Factory, Synapse, Event Hubs, Python, SQL, and Spark.",
    ),
    (
        CloudProfile.GCP,
        "GCP Data Engineer",
        "Required: BigQuery, Dataflow, Dataproc, Pub/Sub, Composer, Python, SQL, and Spark.",
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=(ResumeMode.TAILORED.value, ResumeMode.AI_BULLETS.value),
        default=ResumeMode.TAILORED.value,
    )
    for profile in CloudProfile:
        parser.add_argument(f"--{profile.value}", type=Path)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".data/live-resume-smoke"))
    return parser


def main(argv: list[str] | None = None) -> int:
    if os.getenv("RUN_LIVE_OPENAI_SMOKE") != "1":
        print("SKIP: set RUN_LIVE_OPENAI_SMOKE=1 to run the paid live resume smoke test.")
        return 0
    load_dotenv()
    args = _parser().parse_args(argv)
    if args.mode == ResumeMode.AI_BULLETS.value:
        if args.base is None:
            raise SystemExit("--base is required for ai_bullets smoke mode")
        service = ResumeService(
            mode=ResumeMode.AI_BULLETS,
            paths={},
            ai_resume_path=args.base,
            threshold=20,
            ai_output_dir=args.output_dir,
            api_key=os.getenv("OPENAI_API_KEY", ""),
            review_callback=lambda job, path, digest: True,
        )
        result = service.prepare(
            JobPosting(
                title="Data Engineer",
                description=(
                    "Required: Python and SQL experience building reliable data pipelines "
                    "and governed analytics systems."
                ),
                url="https://www.dice.com/job-detail/synthetic-ai-bullet-live-smoke",
            )
        )
        if not result.eligible or result.prepared is None or not result.prepared.tailored:
            print(f"FAIL ai_bullets: {result.reason}")
            return 1
        print("PASS ai_bullets: reviewed DOCX created with rendered page-count parity")
        return 0

    missing_profiles = [
        profile.value for profile in CloudProfile if getattr(args, profile.value) is None
    ]
    if missing_profiles:
        raise SystemExit(
            "tailored smoke mode requires: "
            + ", ".join(f"--{profile}" for profile in missing_profiles)
        )
    paths = {profile: getattr(args, profile.value) for profile in CloudProfile}
    service = ResumeService(
        mode=ResumeMode.TAILORED,
        paths=paths,
        threshold=20,
        minimum_winner_margin=5,
        output_dir=args.output_dir,
    )

    failures: list[str] = []
    for index, (expected_profile, title, description) in enumerate(SYNTHETIC_JOBS, start=1):
        result = service.prepare(
            JobPosting(
                title=title,
                description=description,
                url=f"https://www.dice.com/job-detail/synthetic-live-smoke-{index}",
            )
        )
        selected = result.decision.selected_profile if result.decision else None
        if (
            not result.eligible
            or result.prepared is None
            or not result.prepared.tailored
            or selected is not expected_profile
        ):
            failures.append(f"{expected_profile.value}: {result.reason}")
            continue
        print(
            f"PASS {expected_profile.value}: tailored DOCX created with rendered page-count parity"
        )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
