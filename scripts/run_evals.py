"""Run the deterministic, credential-free resume matching evaluation set."""

from __future__ import annotations

import json
from pathlib import Path

from core.resumes.models import CloudProfile, JobPosting, ResumeVariant
from core.resumes.selector import (
    ResumeSelector,
    extract_lexical_tokens,
    extract_technology_terms,
)

ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "evals" / "resume_matching.jsonl"

PROFILE_TEXT = {
    CloudProfile.AWS: (
        "AWS data engineer Python SQL Spark Airflow S3 Glue Redshift QuickSight Glue Catalog "
        "Lake Formation Secrets Manager Delta Lake Hadoop HDFS Hive SQL Server Oracle T-SQL "
        "DAX C# .NET"
    ),
    CloudProfile.AZURE: (
        "Azure data engineer Python SQL Spark Data Factory Synapse ADLS Gen2 Azure SQL "
        "Event Hubs Key Vault Azure DevOps Delta Lake Hadoop HDFS Hive SQL Server Oracle "
        "T-SQL DAX C# .NET"
    ),
    CloudProfile.GCP: (
        "GCP data engineer Python SQL Spark BigQuery Dataflow Composer Cloud Functions Dataplex "
        "Cloud Logging Secret Manager Looker Delta Lake Hadoop HDFS Hive SQL Server Oracle "
        "T-SQL DAX C# .NET"
    ),
}


def variant(profile: CloudProfile) -> ResumeVariant:
    text = PROFILE_TEXT[profile]
    return ResumeVariant(
        profile=profile,
        path=Path(f"/{profile.value}.docx"),
        text=text,
        terms=extract_technology_terms(text),
        lexical_tokens=extract_lexical_tokens(text),
    )


def main() -> int:
    selector = ResumeSelector(tuple(variant(profile) for profile in CloudProfile), threshold=30)
    failures: list[str] = []
    total = 0
    for line in EVAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        total += 1
        decision = selector.select(
            JobPosting(
                title=case["title"],
                description=case["description"],
                url=f"https://www.dice.com/job-detail/eval-{total}",
            )
        )
        actual = (
            decision.selected_profile.value,
            decision.eligible,
            list(decision.manual_review_reasons),
        )
        expected = (
            case["expected_profile"],
            case["eligible"],
            case.get("manual_review_reasons", []),
        )
        if actual != expected:
            failures.append(f"{case['name']}: expected {expected}, got {actual}")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"PASS {total} deterministic resume-matching evals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
