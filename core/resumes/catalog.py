"""Privacy-conscious diagnostics for a three-resume catalog."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .documents import collect_skill_slots, extract_resume_text, validate_resume_path
from .models import CloudProfile, ResumeConfigurationError
from .selector import PROFILE_TERMS, extract_technology_terms


@dataclass(frozen=True)
class ResumeInspection:
    """Non-PII diagnostics safe to show before a run."""

    profile: CloudProfile
    format: str
    size_bytes: int
    technology_terms: tuple[str, ...]
    skill_slot_count: int
    skill_item_count: int
    tailored_compatible: bool
    warnings: tuple[str, ...] = ()
    _resolved_path: Path = field(repr=False, compare=False, default=Path())
    _content_digest: str = field(repr=False, compare=False, default="")


def inspect_resume_catalog(
    paths: Mapping[CloudProfile, str | Path],
) -> tuple[ResumeInspection, ...]:
    """Validate and summarize exactly one distinct resume per cloud profile."""

    inspections: list[ResumeInspection] = []
    for profile in CloudProfile:
        path_value = paths.get(profile)
        if not path_value:
            raise ResumeConfigurationError(f"A {profile.value.upper()} resume file is required.")
        path = validate_resume_path(path_value)
        text = extract_resume_text(path)
        terms = extract_technology_terms(text)
        warnings: list[str] = []
        skill_slot_count = 0
        skill_item_count = 0
        tailored_compatible = False

        if not terms.intersection(PROFILE_TERMS[profile]):
            warnings.append(
                f"No explicit {profile.value.upper()} technology evidence was detected."
            )

        if path.suffix.lower() == ".docx":
            try:
                tailored_path = validate_resume_path(path, tailored=True)
                from docx import Document

                slots = collect_skill_slots(Document(str(tailored_path)))
                skill_slot_count = len(slots)
                skill_item_count = sum(len(slot.items) for slot in slots)
                tailored_compatible = bool(slots)
                if not slots:
                    warnings.append("No safely editable delimiter-based skill lists were found.")
            except ResumeConfigurationError as exc:
                warnings.append(str(exc))
        else:
            warnings.append("PDF is supported for static selection only.")

        inspections.append(
            ResumeInspection(
                profile=profile,
                format=path.suffix.lower().lstrip("."),
                size_bytes=path.stat().st_size,
                technology_terms=tuple(sorted(terms)),
                skill_slot_count=skill_slot_count,
                skill_item_count=skill_item_count,
                tailored_compatible=tailored_compatible,
                warnings=tuple(warnings),
                _resolved_path=path,
                _content_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )

    resolved_paths = {inspection._resolved_path for inspection in inspections}
    if len(resolved_paths) != len(CloudProfile):
        raise ResumeConfigurationError("AWS, Azure, and GCP must use three different files.")
    content_digests = {inspection._content_digest for inspection in inspections}
    if len(content_digests) != len(CloudProfile):
        raise ResumeConfigurationError(
            "AWS, Azure, and GCP resumes must have distinct file contents."
        )
    return tuple(inspections)
