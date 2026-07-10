from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from docx import Document

from core.resumes.documents import SkillSlot
from core.resumes.models import JobPosting, ResumeConfigurationError, ResumeTailoringError
from core.resumes.service import ResumeService


class ReversePlanner:
    model = "fake-model"

    def plan(self, job: JobPosting, slots: tuple[SkillSlot, ...]) -> dict[str, Any]:
        slot = slots[0]
        return {
            "schema_version": "1",
            "outcome": "curate",
            "reason_code": "ok",
            "job_evidence": [{"quote": "AWS", "priority": "required"}],
            "slot_orders": [
                {
                    "slot_id": slot.slot_id,
                    "ordered_item_ids": list(reversed(slot.original_order)),
                }
            ],
        }


class ExplodingPlanner:
    model = "fake-model"

    def plan(self, job: JobPosting, slots: tuple[SkillSlot, ...]) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


class CountingReversePlanner(ReversePlanner):
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, job: JobPosting, slots: tuple[SkillSlot, ...]) -> dict[str, Any]:
        self.calls += 1
        return super().plan(job, slots)


def make_paths(resume_factory) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "aws": str(resume_factory("aws.docx", "AWS", ["Python", "SQL", "AWS", "S3", "Glue"])),
        "azure": str(
            resume_factory(
                "azure.docx", "Azure", ["Python", "SQL", "Azure", "Data Factory", "Synapse"]
            )
        ),
        "gcp": str(
            resume_factory("gcp.docx", "GCP", ["Python", "SQL", "GCP", "BigQuery", "Dataflow"])
        ),
    }


def test_static_mode_selects_without_calling_ai(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    service = ResumeService.from_settings(
        {
            "resume_mode": "static",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ExplodingPlanner(),
    )

    result = service.prepare(
        JobPosting(
            title="GCP Data Engineer",
            description="Build GCP BigQuery and Dataflow pipelines with Python and SQL.",
            url="https://www.dice.com/job-detail/static",
        )
    )

    assert result.eligible
    assert result.prepared is not None
    assert result.prepared.path.name == "gcp.docx"
    assert not result.prepared.tailored


def test_tailored_mode_creates_job_specific_copy(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    source_paths = make_paths(resume_factory)
    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": source_paths,
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ReversePlanner(),
        layout_verifier=lambda source, output: None,
    )

    result = service.prepare(
        JobPosting(
            title="AWS Data Engineer",
            description="Required AWS Glue and S3 data pipelines using Python and SQL.",
            url="https://www.dice.com/job-detail/tailored",
        )
    )

    assert result.eligible
    assert result.prepared is not None
    assert result.prepared.tailored
    assert result.prepared.path.exists()
    assert result.prepared.path != Path(source_paths["aws"])


def test_evaluate_does_not_generate_or_call_planner(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ExplodingPlanner(),
        layout_verifier=lambda source, output: None,
    )

    result = service.evaluate(
        JobPosting(
            title="AWS Data Engineer",
            description="Build AWS Glue and S3 pipelines using Python and SQL.",
            url="https://www.dice.com/job-detail/evaluate",
        )
    )

    assert result.eligible
    assert result.prepared is None
    assert not (tmp_path / "out").exists()


def test_page_count_drift_discards_tailored_output(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    def reject_layout(source: Path, output: Path) -> None:
        raise ResumeTailoringError(
            "Tailored resume changed the rendered page count and was discarded."
        )

    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ReversePlanner(),
        layout_verifier=reject_layout,
    )

    result = service.prepare(
        JobPosting(
            title="AWS Data Engineer",
            description="Required AWS Glue and S3 data pipelines using Python and SQL.",
            url="https://www.dice.com/job-detail/layout-drift",
        )
    )

    assert not result.eligible
    assert "page count" in result.reason
    assert not list((tmp_path / "out").glob("*.docx"))


def test_layout_drift_retries_a_smaller_model_consistent_reorder(
    resume_factory, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    verifier_calls = 0

    def accept_second_candidate(source: Path, output: Path) -> None:
        nonlocal verifier_calls
        verifier_calls += 1
        if verifier_calls == 1:
            raise ResumeTailoringError(
                "Tailored resume changed the rendered page count and was discarded."
            )

    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ReversePlanner(),
        layout_verifier=accept_second_candidate,
    )

    result = service.prepare(
        JobPosting(
            title="AWS Data Engineer",
            description="Required AWS Glue and S3 data pipelines using Python and SQL.",
            url="https://www.dice.com/job-detail/layout-fallback",
        )
    )

    assert result.eligible
    assert result.prepared is not None
    assert verifier_calls == 2


def test_duplicate_resume_content_is_rejected(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    aws = resume_factory("aws.docx", "AWS", ["Python", "SQL", "AWS", "S3", "Glue"])
    duplicate = tmp_path / "duplicate.docx"
    duplicate.write_bytes(aws.read_bytes())
    gcp = resume_factory("gcp.docx", "GCP", ["Python", "SQL", "GCP", "BigQuery", "Dataflow"])

    with pytest.raises(ResumeConfigurationError, match="distinct file contents"):
        ResumeService.from_settings(
            {
                "resume_mode": "static",
                "resume_paths": {
                    "aws": str(aws),
                    "azure": str(duplicate),
                    "gcp": str(gcp),
                },
            }
        )


def test_tampered_cached_body_is_regenerated(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    planner = CountingReversePlanner()
    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 20,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=planner,
        layout_verifier=lambda source, output: None,
    )
    job = JobPosting(
        title="AWS Data Engineer",
        description="Required AWS Glue and S3 data pipelines using Python and SQL.",
        url="https://www.dice.com/job-detail/cache-tamper",
    )
    first = service.prepare(job)
    assert first.prepared is not None
    output = first.prepared.path

    tampered = Document(str(output))
    tampered.paragraphs[0].text = "Tampered body text"
    tampered.save(str(output))
    manifest_path = output.with_suffix(f"{output.suffix}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    second = service.prepare(job)

    assert second.eligible
    assert second.prepared is not None
    assert planner.calls == 2
    assert "Tampered body text" not in "\n".join(
        paragraph.text for paragraph in Document(str(second.prepared.path)).paragraphs
    )


def test_low_match_skips_before_curation(resume_factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    service = ResumeService.from_settings(
        {
            "resume_mode": "tailored",
            "resume_paths": make_paths(resume_factory),
            "minimum_match_score": 90,
            "tailored_resume_output_dir": str(tmp_path / "out"),
        },
        planner=ExplodingPlanner(),
    )

    result = service.prepare(
        JobPosting(
            title="Mainframe Administrator",
            description="RACF, COBOL, z/OS, CICS and mainframe security are required.",
            url="https://www.dice.com/job-detail/skip",
        )
    )

    assert not result.eligible
    assert result.prepared is None
