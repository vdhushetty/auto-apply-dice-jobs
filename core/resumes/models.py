"""Typed values shared by the resume pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit


class ResumeError(RuntimeError):
    """Base error for resume preparation failures."""


class ResumeConfigurationError(ResumeError):
    """Raised when resume settings are incomplete or unsafe."""


class ResumeTailoringError(ResumeError):
    """Raised when a tailored resume cannot be produced safely."""


class ResumeMode(StrEnum):
    """Supported resume preparation modes."""

    STATIC = "static"
    TAILORED = "tailored"

    @classmethod
    def parse(cls, value: str) -> ResumeMode:
        normalized = value.strip().lower()
        aliases = {
            "static selection": cls.STATIC,
            "curated": cls.TAILORED,
            "tailored per job": cls.TAILORED,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            supported = ", ".join(mode.value for mode in cls)
            raise ResumeConfigurationError(
                f"Unsupported resume mode '{value}'. Expected one of: {supported}."
            ) from exc


class CloudProfile(StrEnum):
    """The three candidate resume variants supported by the product."""

    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


@dataclass(frozen=True)
class JobPosting:
    """Job information used for matching and curation."""

    title: str
    description: str
    url: str
    job_id: str = ""

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("A job title is required.")
        if not self.description.strip():
            raise ValueError("A job description is required.")
        parsed_url = urlsplit(self.url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "www.dice.com"
            or not parsed_url.path.startswith("/job-detail/")
        ):
            raise ValueError("Only Dice job URLs are accepted.")


@dataclass(frozen=True)
class ResumeVariant:
    """A validated source resume and its extracted text."""

    profile: CloudProfile
    path: Path
    text: str
    terms: frozenset[str]
    lexical_tokens: frozenset[str]


@dataclass(frozen=True)
class MatchDecision:
    """Transparent result of comparing one job with all variants."""

    selected_profile: CloudProfile
    selected_path: Path
    score: float
    threshold: float
    eligible: bool
    matched_terms: tuple[str, ...] = ()
    missing_terms: tuple[str, ...] = ()
    missing_required_terms: tuple[str, ...] = ()
    ambiguous: bool = False
    variant_scores: dict[str, float] = field(default_factory=dict)
    score_margin: float = 0.0
    minimum_winner_margin: float = 0.0
    explicit_title_profile: CloudProfile | None = None
    manual_review_reasons: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if self.manual_review_reasons:
            reasons = ", ".join(self.manual_review_reasons)
            return f"Manual review required before applying: {reasons}."
        if self.ambiguous:
            return (
                "The top resume scores were tied or too close "
                f"({self.score_margin:.1f}-point margin; "
                f"{self.minimum_winner_margin:.1f} required); skipped because there was no "
                "confident unique best match."
            )
        if self.missing_required_terms:
            terms = ", ".join(self.missing_required_terms)
            return f"Selected resume is missing required job terms: {terms}."
        if self.eligible:
            return f"Selected {self.selected_profile.value.upper()} at {self.score:.1f}% match."
        selection_label = "Selected resume" if self.explicit_title_profile else "Best resume"
        return (
            f"{selection_label} match was {self.score:.1f}%, below the configured "
            f"{self.threshold:.1f}% threshold."
        )


@dataclass(frozen=True)
class PreparedResume:
    """A source or generated file approved for upload."""

    path: Path
    decision: MatchDecision
    tailored: bool


@dataclass(frozen=True)
class ResumePreparation:
    """Fail-closed outcome returned to the browser layer."""

    eligible: bool
    reason: str
    decision: MatchDecision | None = None
    prepared: PreparedResume | None = None
