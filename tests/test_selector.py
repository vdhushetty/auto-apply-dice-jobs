from __future__ import annotations

from pathlib import Path

import pytest

from core.resumes.models import CloudProfile, CustomProfile, JobPosting, ResumeVariant
from core.resumes.selector import (
    ResumeSelector,
    SingleResumeSelector,
    detect_manual_review_reasons,
    extract_lexical_tokens,
    extract_required_technology_terms,
    extract_technology_terms,
)


def variant(profile: CloudProfile, text: str) -> ResumeVariant:
    return ResumeVariant(
        profile=profile,
        path=Path(f"/{profile.value}.docx"),
        text=text,
        terms=extract_technology_terms(text),
        lexical_tokens=extract_lexical_tokens(text),
    )


@pytest.fixture
def variants() -> tuple[ResumeVariant, ...]:
    common = "Delta Lake Hadoop HDFS Hive SQL Server Oracle T-SQL DAX C# .NET"
    return (
        variant(
            CloudProfile.AWS,
            f"AWS data engineer Python SQL Spark S3 Glue Redshift QuickSight Glue Catalog "
            f"Lake Formation Secrets Manager {common}",
        ),
        variant(
            CloudProfile.AZURE,
            f"Azure data engineer Python SQL Databricks Data Factory Synapse ADLS Gen2 "
            f"Azure SQL Event Hubs Key Vault Azure DevOps {common}",
        ),
        variant(
            CloudProfile.GCP,
            f"GCP data engineer Python SQL BigQuery Dataflow Composer Cloud Functions Dataplex "
            f"Cloud Logging Secret Manager Looker {common}",
        ),
    )


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        (
            "AWS Data Engineer",
            "Required: AWS Glue, S3, Redshift, Python, SQL and Spark.",
            CloudProfile.AWS,
        ),
        (
            "Azure Data Engineer",
            "Build Azure Data Factory and Synapse pipelines with Python and SQL.",
            CloudProfile.AZURE,
        ),
        (
            "GCP Data Engineer",
            "Required experience with BigQuery, Dataflow, Composer, Python and SQL.",
            CloudProfile.GCP,
        ),
    ],
)
def test_selects_best_cloud_variant(
    variants: tuple[ResumeVariant, ...],
    title: str,
    description: str,
    expected: CloudProfile,
) -> None:
    decision = ResumeSelector(variants, threshold=30).select(
        JobPosting(title=title, description=description, url="https://www.dice.com/job-detail/1")
    )

    assert decision.eligible
    assert decision.selected_profile is expected
    assert decision.score >= 30


def test_low_match_job_is_skipped(variants: tuple[ResumeVariant, ...]) -> None:
    decision = ResumeSelector(variants, threshold=55).select(
        JobPosting(
            title="Mainframe Security Administrator",
            description="Required RACF, z/OS, COBOL, CICS, and security operations expertise.",
            url="https://www.dice.com/job-detail/2",
        )
    )

    assert not decision.eligible
    assert decision.score < 55


def test_tied_cloud_neutral_job_is_skipped(variants: tuple[ResumeVariant, ...]) -> None:
    decision = ResumeSelector(variants, threshold=20).select(
        JobPosting(
            title="Data Engineer",
            description="Build Python SQL data pipelines.",
            url="https://www.dice.com/job-detail/tied",
        )
    )

    assert not decision.eligible
    assert decision.ambiguous
    assert "tied" in decision.reason


def test_missing_explicit_requirement_is_skipped(
    variants: tuple[ResumeVariant, ...],
) -> None:
    decision = ResumeSelector(variants, threshold=20).select(
        JobPosting(
            title="AWS Data Engineer",
            description="Required: AWS, S3, Python, SQL, Spark, and Kubernetes.",
            url="https://www.dice.com/job-detail/missing-required",
        )
    )

    assert not decision.eligible
    assert decision.missing_required_terms == ("kubernetes",)
    assert "required" in decision.reason


def test_job_requires_description() -> None:
    with pytest.raises(ValueError, match="description"):
        JobPosting(
            title="Data Engineer",
            description=" ",
            url="https://www.dice.com/job-detail/3",
        )


def test_job_rejects_lookalike_dice_host() -> None:
    with pytest.raises(ValueError, match="Dice job URLs"):
        JobPosting(
            title="Data Engineer",
            description="A sufficiently descriptive data engineering role.",
            url="https://www.dice.com.example.test/job-detail/3",
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "ADLS Gen2, Azure SQL, Event Hubs, Key Vault, and Azure DevOps",
            {
                "azure-adls-gen2",
                "azure-sql",
                "azure-event-hubs",
                "azure-key-vault",
                "azure-devops",
            },
        ),
        (
            "QuickSight, Glue Catalog, Lake Formation, and AWS Secrets Manager",
            {
                "aws-quicksight",
                "aws-glue-catalog",
                "aws-lake-formation",
                "aws-secrets-manager",
            },
        ),
        (
            "Cloud Functions, Dataplex, Cloud Logging, Secret Manager, and Looker",
            {
                "gcp-cloud-functions",
                "gcp-dataplex",
                "gcp-cloud-logging",
                "gcp-secret-manager",
                "gcp-looker",
            },
        ),
        (
            "Delta Lake, Hadoop, HDFS, Hive, SQL Server, Oracle, T-SQL, DAX, C#, and .NET",
            {
                "delta-lake",
                "hadoop",
                "hdfs",
                "hive",
                "sql-server",
                "oracle",
                "t-sql",
                "dax",
                "c-sharp",
                "dotnet",
            },
        ),
    ],
)
def test_extracts_sample_resume_technology_terms(text: str, expected: set[str]) -> None:
    assert expected <= extract_technology_terms(text)


def test_required_bullets_are_parsed_until_next_heading() -> None:
    description = """
Requirements:
- ADLS Gen2
* Azure SQL
• Event Hubs and Key Vault
4. Azure DevOps

Preferred Qualifications:
- Kubernetes
"""

    required = extract_required_technology_terms(description)

    assert {
        "azure-adls-gen2",
        "azure-sql",
        "azure-event-hubs",
        "azure-key-vault",
        "azure-devops",
    } <= required
    assert "kubernetes" not in required


@pytest.mark.parametrize(
    ("constraint", "expected_reason"),
    [
        ("Active TS/SCI required.", "clearance requirement"),
        (
            "Candidates must be U.S. citizens.",
            "citizenship or sponsorship restriction",
        ),
        ("W2 candidates only; no C-2-C arrangements.", "W2-only or no-C2C restriction"),
        (
            "Onsite 3 days per week; relocation is required.",
            "onsite or relocation requirement",
        ),
    ],
)
def test_manual_review_constraints_fail_closed(
    variants: tuple[ResumeVariant, ...], constraint: str, expected_reason: str
) -> None:
    decision = ResumeSelector(variants, threshold=20).select(
        JobPosting(
            title="AWS Data Engineer",
            description=f"Required AWS Glue, S3, Python, and SQL. {constraint}",
            url="https://www.dice.com/job-detail/manual-review",
        )
    )

    assert not decision.eligible
    assert expected_reason in decision.manual_review_reasons
    assert "Manual review required" in decision.reason


def test_clearance_negation_does_not_trigger_manual_review() -> None:
    assert (
        detect_manual_review_reasons(
            "No security clearance is required. This role is fully remote."
        )
        == ()
    )


def test_close_non_explicit_match_is_ambiguous() -> None:
    close_variants = (
        ResumeVariant(
            CloudProfile.AWS,
            Path("/aws.docx"),
            "",
            frozenset(),
            frozenset({"platform", "alpha", "beta", "gamma"}),
        ),
        ResumeVariant(
            CloudProfile.AZURE,
            Path("/azure.docx"),
            "",
            frozenset(),
            frozenset({"platform", "alpha", "beta"}),
        ),
        ResumeVariant(
            CloudProfile.GCP,
            Path("/gcp.docx"),
            "",
            frozenset(),
            frozenset({"platform", "alpha"}),
        ),
    )
    job = JobPosting(
        title="Platform Specialist",
        description="Alpha beta gamma delta epsilon zeta eta theta iota kappa.",
        url="https://www.dice.com/job-detail/close-match",
    )

    decision = ResumeSelector(close_variants, threshold=10).select(job)

    assert decision.selected_profile is CloudProfile.AWS
    assert 0 < decision.score_margin < decision.minimum_winner_margin
    assert decision.ambiguous
    assert not decision.eligible
    assert (
        ResumeSelector(close_variants, threshold=10, minimum_winner_margin=1).select(job).eligible
    )


def test_explicit_single_cloud_in_title_routes_that_profile() -> None:
    cross_cloud_variants = (
        variant(CloudProfile.AWS, "AWS platform operations"),
        variant(CloudProfile.AZURE, "Azure AWS data engineer Python SQL Spark"),
        variant(CloudProfile.GCP, "GCP data engineer Python SQL Spark"),
    )

    decision = ResumeSelector(cross_cloud_variants, threshold=20).select(
        JobPosting(
            title="AWS Data Engineer",
            description="Build Python SQL and Spark data pipelines.",
            url="https://www.dice.com/job-detail/explicit-aws",
        )
    )

    assert decision.variant_scores["azure"] > decision.variant_scores["aws"]
    assert decision.selected_profile is CloudProfile.AWS
    assert decision.explicit_title_profile is CloudProfile.AWS


def test_single_resume_selector_reports_custom_profile() -> None:
    custom = ResumeVariant(
        profile=CustomProfile.CUSTOM,
        path=Path("/base.docx"),
        text="AWS data engineer Python SQL Glue S3",
        terms=extract_technology_terms("AWS data engineer Python SQL Glue S3"),
        lexical_tokens=extract_lexical_tokens("AWS data engineer Python SQL Glue S3"),
    )

    decision = SingleResumeSelector(custom, threshold=20).select(
        JobPosting(
            title="AWS Data Engineer",
            description="Required: AWS Glue, S3, Python, and SQL.",
            url="https://www.dice.com/job-detail/custom",
        )
    )

    assert decision.eligible
    assert decision.selected_profile is CustomProfile.CUSTOM
    assert decision.variant_scores == {"custom": decision.score}
    assert "Custom base resume" in decision.reason
    assert not decision.ambiguous


def test_single_resume_selector_fails_closed_on_missing_required_term() -> None:
    custom = ResumeVariant(
        profile=CustomProfile.CUSTOM,
        path=Path("/base.docx"),
        text="Data engineer Python SQL",
        terms=extract_technology_terms("Data engineer Python SQL"),
        lexical_tokens=extract_lexical_tokens("Data engineer Python SQL"),
    )

    decision = SingleResumeSelector(custom, threshold=0).select(
        JobPosting(
            title="GCP Data Engineer",
            description="Requirements:\n- GCP\n- BigQuery\n- Python\n- SQL",
            url="https://www.dice.com/job-detail/custom-missing",
        )
    )

    assert not decision.eligible
    assert {"gcp", "gcp-bigquery"} <= set(decision.missing_required_terms)
    assert not decision.ambiguous


@pytest.mark.parametrize("margin", [-1, 101])
def test_rejects_invalid_minimum_winner_margin(
    variants: tuple[ResumeVariant, ...], margin: float
) -> None:
    with pytest.raises(ValueError, match="winner margin"):
        ResumeSelector(variants, threshold=30, minimum_winner_margin=margin)
