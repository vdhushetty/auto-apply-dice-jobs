from pathlib import Path

from core.resumes.catalog import inspect_resume_catalog
from core.resumes.models import CloudProfile


def test_catalog_reports_tailored_compatibility(resume_factory) -> None:  # type: ignore[no-untyped-def]
    paths = {
        CloudProfile.AWS: resume_factory("aws.docx", "AWS", ["Python", "SQL", "AWS", "S3", "Glue"]),
        CloudProfile.AZURE: resume_factory(
            "azure.docx",
            "Azure",
            ["Python", "SQL", "Azure", "Data Factory", "Synapse"],
        ),
        CloudProfile.GCP: resume_factory(
            "gcp.docx", "GCP", ["Python", "SQL", "GCP", "BigQuery", "Dataflow"]
        ),
    }

    inspections = inspect_resume_catalog(paths)

    assert [inspection.profile for inspection in inspections] == list(CloudProfile)
    assert all(inspection.format == "docx" for inspection in inspections)
    assert all(inspection.tailored_compatible for inspection in inspections)
    assert all(inspection.skill_slot_count == 1 for inspection in inspections)
    assert all(inspection.skill_item_count == 5 for inspection in inspections)
    assert all(
        inspection._resolved_path == Path(paths[inspection.profile]).resolve()
        for inspection in inspections
    )
