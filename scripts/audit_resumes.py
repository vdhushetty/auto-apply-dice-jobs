"""Audit three resumes and optionally preview one local job match without network calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.resumes import JobPosting, ResumeService, inspect_resume_catalog
from core.resumes.models import CloudProfile, ResumeMode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect AWS/Azure/GCP resumes without printing their contents or paths."
    )
    for profile in CloudProfile:
        parser.add_argument(f"--{profile.value}", required=True, type=Path)
    parser.add_argument("--minimum-score", type=float, default=35.0)
    parser.add_argument("--winner-margin", type=float, default=5.0)
    parser.add_argument("--job-title")
    parser.add_argument("--job-description-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = {profile: getattr(args, profile.value) for profile in CloudProfile}
    inspections = inspect_resume_catalog(paths)
    payload: dict[str, object] = {
        "resumes": [
            {
                "profile": inspection.profile.value,
                "format": inspection.format,
                "size_bytes": inspection.size_bytes,
                "recognized_term_count": len(inspection.technology_terms),
                "skill_slot_count": inspection.skill_slot_count,
                "skill_item_count": inspection.skill_item_count,
                "tailored_compatible": inspection.tailored_compatible,
                "warnings": list(inspection.warnings),
            }
            for inspection in inspections
        ]
    }

    if bool(args.job_title) != bool(args.job_description_file):
        raise SystemExit("--job-title and --job-description-file must be provided together.")
    if args.job_title and args.job_description_file:
        description = args.job_description_file.read_text(encoding="utf-8")
        service = ResumeService(
            mode=ResumeMode.STATIC,
            paths=paths,
            threshold=args.minimum_score,
            minimum_winner_margin=args.winner_margin,
        )
        evaluation = service.evaluate(
            JobPosting(
                title=args.job_title,
                description=description,
                url="https://www.dice.com/job-detail/local-offline-preview",
            )
        )
        decision = evaluation.decision
        payload["match"] = {
            "eligible": evaluation.eligible,
            "reason": evaluation.reason,
            "selected_profile": decision.selected_profile.value if decision else None,
            "score": decision.score if decision else None,
            "variant_scores": decision.variant_scores if decision else {},
            "missing_required_terms": list(decision.missing_required_terms) if decision else [],
            "manual_review_reasons": list(decision.manual_review_reasons) if decision else [],
        }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
