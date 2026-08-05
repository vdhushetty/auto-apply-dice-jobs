"""Run the deterministic, credential-free resume matching evaluation set."""

from __future__ import annotations

import json
from pathlib import Path

from core.resumes.bullet_curator import EditableBullet, validate_bullet_rewrite_plan
from core.resumes.models import (
    CloudProfile,
    CustomProfile,
    JobPosting,
    ResumeTailoringError,
    ResumeVariant,
)
from core.resumes.selector import (
    ResumeSelector,
    SingleResumeSelector,
    extract_lexical_tokens,
    extract_technology_terms,
)

ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "evals" / "resume_matching.jsonl"
SINGLE_RESUME_EVAL_FILE = ROOT / "evals" / "single_resume_matching.jsonl"

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


def run_bullet_validation_evals(failures: list[str]) -> int:
    """Exercise the AI-bullet prompt contract without making an API call."""

    source_text = (
        "Built AWS data pipelines with Python and SQL, processed 10 TB, and reduced latency "
        "by 20 percent."
    )
    bullet = EditableBullet(
        bullet_id="bullet-0001",
        text=source_text,
        section="experience",
        group_id="group-0001",
    )
    other_role = EditableBullet(
        bullet_id="bullet-0002",
        text="Built GCP BigQuery workflows for a different role.",
        section="experience",
        group_id="group-0002",
    )
    resume_text = f"{source_text}\n{other_role.text}"
    job = JobPosting(
        title="AWS Data Engineer",
        description="Required: AWS, Python, and SQL data pipeline experience.",
        url="https://www.dice.com/job-detail/bullet-eval",
    )
    cases = (
        (
            "bullet_safe_rewrite",
            "Built reliable AWS data pipelines with Python and SQL, processing 10 TB and "
            "reducing latency by 20 percent.",
            True,
        ),
        (
            "bullet_cross_role_technology_misattribution",
            "Built GCP BigQuery pipelines with Python and SQL, processing 10 TB and reducing "
            "latency by 20 percent.",
            False,
        ),
        (
            "bullet_metric_mutation",
            "Built reliable AWS pipelines with Python and SQL, processing 10 TB and reducing "
            "latency by 40 percent.",
            False,
        ),
        (
            "bullet_metric_unit_mutation",
            "Built reliable AWS pipelines with Python and SQL, processing 10 PB and reducing "
            "latency by 20 percent.",
            False,
        ),
    )
    for name, replacement, expected_accepted in cases:
        raw_plan = {
            "schema_version": "1",
            "outcome": "rewrite",
            "reason_code": "ok",
            "job_evidence": [{"quote": "AWS", "priority": "required"}],
            "edits": [
                {
                    "bullet_id": bullet.bullet_id,
                    "replacement_bullets": [replacement],
                    "source_bullet_ids": [bullet.bullet_id],
                }
            ],
        }
        accepted = True
        try:
            validate_bullet_rewrite_plan(raw_plan, job, (bullet, other_role), resume_text)
        except ResumeTailoringError:
            accepted = False
        if accepted is not expected_accepted:
            failures.append(
                f"{name}: expected accepted={expected_accepted}, got accepted={accepted}"
            )
    return len(cases)


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

    custom_text = PROFILE_TEXT[CloudProfile.AWS]
    custom_variant = ResumeVariant(
        profile=CustomProfile.CUSTOM,
        path=Path("/custom.docx"),
        text=custom_text,
        terms=extract_technology_terms(custom_text),
        lexical_tokens=extract_lexical_tokens(custom_text),
    )
    single_selector = SingleResumeSelector(custom_variant, threshold=30)
    for line in SINGLE_RESUME_EVAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        total += 1
        decision = single_selector.select(
            JobPosting(
                title=case["title"],
                description=case["description"],
                url=f"https://www.dice.com/job-detail/single-eval-{total}",
            )
        )
        actual = (
            decision.selected_profile.value,
            decision.eligible,
            list(decision.missing_required_terms),
            list(decision.manual_review_reasons),
        )
        expected = (
            "custom",
            case["eligible"],
            case.get("missing_required_terms", []),
            case.get("manual_review_reasons", []),
        )
        if actual != expected:
            failures.append(f"{case['name']}: expected {expected}, got {actual}")
    total += run_bullet_validation_evals(failures)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"PASS {total} deterministic resume-matching evals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
