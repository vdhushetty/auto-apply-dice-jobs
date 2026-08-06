"""Evidence-grounded data and validation for AI resume bullet rewrites."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .models import JobPosting, ResumeTailoringError
from .selector import extract_technology_terms

BULLET_REWRITE_PROMPT_VERSION = "resume-bullet-rewrite-v2"
DEFAULT_BULLET_REWRITE_MODEL = "gpt-5.6-sol"
MAX_EDITED_BULLETS = 4
MAX_NET_NEW_BULLETS = 2
MAX_REPLACEMENTS_PER_EDIT = 2
MAX_SOURCE_BULLETS_PER_EDIT = 4
MAX_REPLACEMENT_BULLET_CHARS = 500
MAX_EDITABLE_BULLETS = 80
MAX_BULLET_ID_CHARS = 128
MAX_GROUP_ID_CHARS = 128
MAX_JOB_EVIDENCE_ITEMS = 8
MAX_JOB_EVIDENCE_CHARS = 300

_REWRITE_REASON_CODES = frozenset(
    {
        "ok",
        "insufficient_source_evidence",
        "no_relevant_change",
        "ambiguous_job",
        "unsafe_to_rewrite",
    }
)
_NON_OK_REASON_CODES = _REWRITE_REASON_CODES - {"ok"}
_PLAN_FIELDS = frozenset({"schema_version", "outcome", "reason_code", "job_evidence", "edits"})
_EVIDENCE_FIELDS = frozenset({"quote", "priority"})
_EDIT_FIELDS = frozenset({"bullet_id", "replacement_bullets", "source_bullet_ids"})
_EVIDENCE_PRIORITIES = frozenset({"required", "preferred", "context"})

BULLET_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "enum": ["1"]},
        "outcome": {"type": "string", "enum": ["rewrite", "no_safe_plan"]},
        "reason_code": {
            "type": "string",
            "enum": sorted(_REWRITE_REASON_CODES),
        },
        "job_evidence": {
            "type": "array",
            "maxItems": MAX_JOB_EVIDENCE_ITEMS,
            "items": {
                "type": "object",
                "properties": {
                    "quote": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_JOB_EVIDENCE_CHARS,
                    },
                    "priority": {
                        "type": "string",
                        "enum": sorted(_EVIDENCE_PRIORITIES),
                    },
                },
                "required": ["quote", "priority"],
                "additionalProperties": False,
            },
        },
        "edits": {
            "type": "array",
            "maxItems": MAX_EDITED_BULLETS,
            "items": {
                "type": "object",
                "properties": {
                    "bullet_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_BULLET_ID_CHARS,
                    },
                    "replacement_bullets": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_REPLACEMENTS_PER_EDIT,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_REPLACEMENT_BULLET_CHARS,
                        },
                    },
                    "source_bullet_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_SOURCE_BULLETS_PER_EDIT,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_BULLET_ID_CHARS,
                        },
                    },
                },
                "required": ["bullet_id", "replacement_bullets", "source_bullet_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema_version", "outcome", "reason_code", "job_evidence", "edits"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class EditableBullet:
    """One candidate-authored bullet that may be rewritten in place."""

    bullet_id: str
    text: str
    section: str
    group_id: str


@dataclass(frozen=True)
class ValidatedBulletEdit:
    """A locally validated one-for-one or one-for-two bullet replacement."""

    bullet_id: str
    replacement_bullets: tuple[str, ...]
    source_bullet_ids: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedBulletRewritePlan:
    """The bounded set of bullet edits approved for document rendering."""

    edits: tuple[ValidatedBulletEdit, ...]
    reason_code: str


class BulletRewritePlanner(Protocol):
    """Injection seam for the sole OpenAI boundary and offline fakes."""

    model: str

    def plan(self, job: JobPosting, bullets: Sequence[EditableBullet]) -> Mapping[str, Any]: ...


# The selector taxonomy covers the technologies used by matching. These additional aliases
# close common injection gaps without treating every new prose word as a technology.
_ADDITIONAL_TECHNOLOGY_ALIASES: dict[str, tuple[str, ...]] = {
    "ansible": ("ansible",),
    "c-plus-plus": ("c++",),
    "cassandra": ("cassandra",),
    "cobol": ("cobol",),
    "elasticsearch": ("elasticsearch", "elastic search"),
    "fastapi": ("fastapi",),
    "flink": ("apache flink", "flink"),
    "github-actions": ("github actions",),
    "gitlab": ("gitlab",),
    "golang": ("golang", "go language"),
    "grafana": ("grafana",),
    "graphql": ("graphql",),
    "javascript": ("javascript",),
    "jenkins": ("jenkins",),
    "keras": ("keras",),
    "mongodb": ("mongodb", "mongo db"),
    "mysql": ("mysql",),
    "nodejs": ("node.js", "nodejs"),
    "postgresql": ("postgresql", "postgres"),
    "pytorch": ("pytorch",),
    "ruby": ("ruby on rails", "ruby"),
    "react": ("react.js", "reactjs", "react"),
    "redis": ("redis",),
    "rust": ("rust language", "rust"),
    "sas": ("sas analytics", "sas"),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "splunk": ("splunk",),
    "tensorflow": ("tensorflow",),
    "typescript": ("typescript",),
}


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias).replace(r"\ ", r"[\s/-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


_COMPILED_ADDITIONAL_TECHNOLOGIES = tuple(
    (canonical, _alias_pattern(alias))
    for canonical, aliases in _ADDITIONAL_TECHNOLOGY_ALIASES.items()
    for alias in aliases
)
_NUMERIC_PATTERN = r"\d+(?:,\d{3})*(?:\.\d+)?"
_NUMERIC_TOKEN = re.compile(_NUMERIC_PATTERN)
_QUANTIFIED_NUMBER = re.compile(
    rf"(?P<number>{_NUMERIC_PATTERN})\s*"
    r"(?P<unit>%|percent(?:age)?s?|"
    r"(?:k|m|g|t|p|e)i?b|bytes?|kilobytes?|megabytes?|gigabytes?|terabytes?|petabytes?|"
    r"milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"thousands?|millions?|billions?|trillions?|usd|dollars?|x|times|fold)"
    r"(?![a-z])",
    re.IGNORECASE,
)
_CURRENCY_NUMBER = re.compile(
    rf"(?P<unit>[$€£])\s*(?P<number>{_NUMERIC_PATTERN})",
    re.IGNORECASE,
)
_QUANTITY_UNIT_ALIASES: dict[str, str] = {
    "%": "percent",
    "percentage": "percent",
    "percentages": "percent",
    "percents": "percent",
    "b": "byte",
    "byte": "byte",
    "bytes": "byte",
    "kb": "kb",
    "kilobyte": "kb",
    "kilobytes": "kb",
    "mb": "mb",
    "megabyte": "mb",
    "megabytes": "mb",
    "gb": "gb",
    "gigabyte": "gb",
    "gigabytes": "gb",
    "tb": "tb",
    "terabyte": "tb",
    "terabytes": "tb",
    "pb": "pb",
    "petabyte": "pb",
    "petabytes": "pb",
    "millisecond": "millisecond",
    "milliseconds": "millisecond",
    "second": "second",
    "seconds": "second",
    "minute": "minute",
    "minutes": "minute",
    "hour": "hour",
    "hours": "hour",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
    "thousand": "thousand",
    "thousands": "thousand",
    "million": "million",
    "millions": "million",
    "billion": "billion",
    "billions": "billion",
    "trillion": "trillion",
    "trillions": "trillion",
    "dollar": "usd",
    "dollars": "usd",
    "$": "usd",
    "€": "eur",
    "£": "gbp",
    "times": "x",
    "fold": "x",
}


def _technology_terms(text: str) -> frozenset[str]:
    terms = set(extract_technology_terms(text))
    terms.update(
        canonical
        for canonical, pattern in _COMPILED_ADDITIONAL_TECHNOLOGIES
        if pattern.search(text)
    )
    return frozenset(terms)


def _numeric_tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(0).replace(",", "") for match in _NUMERIC_TOKEN.finditer(text))


def _numeric_quantity_claims(text: str) -> frozenset[tuple[str, str]]:
    claims = {
        (
            match.group("number").replace(",", ""),
            _QUANTITY_UNIT_ALIASES.get(
                match.group("unit").casefold(), match.group("unit").casefold()
            ),
        )
        for match in _QUANTIFIED_NUMBER.finditer(text)
    }
    claims.update(
        (
            match.group("number").replace(",", ""),
            _QUANTITY_UNIT_ALIASES[match.group("unit").casefold()],
        )
        for match in _CURRENCY_NUMBER.finditer(text)
    )
    return frozenset(claims)


def _normalized_text(text: str) -> str:
    normalized = " ".join(text.split()).casefold()
    return normalized.strip(" .,:;!?")


def _require_exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise ResumeTailoringError(f"Bullet rewrite {label} has missing or unknown fields.")


def _validate_job_evidence(raw_evidence: Any, job: JobPosting, *, required: bool) -> None:
    if not isinstance(raw_evidence, list):
        raise ResumeTailoringError("Bullet rewrite job evidence must be a list.")
    if len(raw_evidence) > MAX_JOB_EVIDENCE_ITEMS or (required and not raw_evidence):
        raise ResumeTailoringError("Bullet rewrite job evidence is missing or exceeds its limit.")

    job_text = f"{job.title}\n{job.description}"
    seen_quotes: set[str] = set()
    for evidence in raw_evidence:
        if not isinstance(evidence, Mapping):
            raise ResumeTailoringError("Bullet rewrite job evidence is invalid.")
        _require_exact_fields(evidence, _EVIDENCE_FIELDS, "job evidence")
        quote = evidence.get("quote")
        priority = evidence.get("priority")
        if (
            not isinstance(quote, str)
            or not quote.strip()
            or not 1 <= len(quote) <= MAX_JOB_EVIDENCE_CHARS
            or quote not in job_text
        ):
            raise ResumeTailoringError(
                "Bullet rewrite evidence is not an exact substring of the job posting."
            )
        if not isinstance(priority, str) or priority not in _EVIDENCE_PRIORITIES:
            raise ResumeTailoringError("Bullet rewrite evidence priority is invalid.")
        if quote in seen_quotes:
            raise ResumeTailoringError("Bullet rewrite evidence contains a duplicate quote.")
        seen_quotes.add(quote)


def _index_bullets(bullets: Sequence[EditableBullet]) -> dict[str, EditableBullet]:
    if not 1 <= len(bullets) <= MAX_EDITABLE_BULLETS:
        raise ResumeTailoringError("Editable resume bullets are missing or exceed the limit.")
    indexed: dict[str, EditableBullet] = {}
    for bullet in bullets:
        if (
            not isinstance(bullet.bullet_id, str)
            or not isinstance(bullet.text, str)
            or not isinstance(bullet.section, str)
            or not isinstance(bullet.group_id, str)
            or not bullet.bullet_id.strip()
            or len(bullet.bullet_id) > MAX_BULLET_ID_CHARS
            or not bullet.text.strip()
            or len(bullet.text) > MAX_REPLACEMENT_BULLET_CHARS
            or not bullet.section.strip()
            or not bullet.group_id.strip()
            or len(bullet.group_id) > MAX_GROUP_ID_CHARS
        ):
            raise ResumeTailoringError("Editable resume bullets contain an invalid field.")
        if bullet.bullet_id in indexed:
            raise ResumeTailoringError("Editable resume bullets contain a duplicate ID.")
        indexed[bullet.bullet_id] = bullet
    return indexed


def validate_bullet_rewrite_plan(
    raw_plan: Mapping[str, Any],
    job: JobPosting,
    bullets: Sequence[EditableBullet],
    resume_text: str,
) -> ValidatedBulletRewritePlan:
    """Validate every model-provided edit locally and fail closed on uncertainty."""

    if not isinstance(raw_plan, Mapping):
        raise ResumeTailoringError("Bullet rewrite plan is not an object.")
    _require_exact_fields(raw_plan, _PLAN_FIELDS, "plan")
    if raw_plan.get("schema_version") != "1":
        raise ResumeTailoringError("Bullet rewrite plan has an unsupported schema version.")

    outcome = raw_plan.get("outcome")
    reason_code = raw_plan.get("reason_code")
    raw_edits = raw_plan.get("edits")
    if not isinstance(reason_code, str) or reason_code not in _REWRITE_REASON_CODES:
        raise ResumeTailoringError("Bullet rewrite plan has an invalid reason code.")
    if not isinstance(raw_edits, list):
        raise ResumeTailoringError("Bullet rewrite edits must be a list.")

    if outcome == "no_safe_plan":
        if reason_code not in _NON_OK_REASON_CODES or raw_edits:
            raise ResumeTailoringError("No-safe bullet rewrite outcome is inconsistent.")
        _validate_job_evidence(raw_plan.get("job_evidence"), job, required=False)
        raise ResumeTailoringError(f"No safe bullet rewrite plan: {reason_code}.")
    if outcome != "rewrite" or reason_code != "ok":
        raise ResumeTailoringError("Bullet rewrite plan outcome is inconsistent.")
    if not 1 <= len(raw_edits) <= MAX_EDITED_BULLETS:
        raise ResumeTailoringError("Bullet rewrite plan must edit between one and four bullets.")
    _validate_job_evidence(raw_plan.get("job_evidence"), job, required=True)

    bullets_by_id = _index_bullets(bullets)
    if not bullets_by_id:
        raise ResumeTailoringError("No editable resume bullets were supplied.")
    if not isinstance(resume_text, str) or not resume_text.strip():
        raise ResumeTailoringError("Source resume text is required for bullet rewrite validation.")
    resume_technologies = _technology_terms(resume_text)

    seen_edit_ids: set[str] = set()
    seen_replacement_texts: set[str] = set()
    net_new_bullets = 0
    validated_edits: list[ValidatedBulletEdit] = []
    for raw_edit in raw_edits:
        if not isinstance(raw_edit, Mapping):
            raise ResumeTailoringError("Bullet rewrite edit is invalid.")
        _require_exact_fields(raw_edit, _EDIT_FIELDS, "edit")

        bullet_id = raw_edit.get("bullet_id")
        if not isinstance(bullet_id, str) or bullet_id not in bullets_by_id:
            raise ResumeTailoringError("Bullet rewrite referenced an unknown bullet ID.")
        if bullet_id in seen_edit_ids:
            raise ResumeTailoringError("Bullet rewrite referenced a duplicate edit bullet ID.")
        seen_edit_ids.add(bullet_id)
        target = bullets_by_id[bullet_id]

        raw_sources = raw_edit.get("source_bullet_ids")
        if (
            not isinstance(raw_sources, list)
            or not 1 <= len(raw_sources) <= MAX_SOURCE_BULLETS_PER_EDIT
            or not all(isinstance(source_id, str) for source_id in raw_sources)
        ):
            raise ResumeTailoringError("Bullet rewrite source IDs are invalid or exceed the limit.")
        source_ids = tuple(raw_sources)
        if len(set(source_ids)) != len(source_ids):
            raise ResumeTailoringError("Bullet rewrite contains duplicate source bullet IDs.")
        try:
            source_bullets = tuple(bullets_by_id[source_id] for source_id in source_ids)
        except KeyError as exc:
            raise ResumeTailoringError(
                "Bullet rewrite referenced an unknown source bullet ID."
            ) from exc
        if any(source.group_id != target.group_id for source in source_bullets):
            raise ResumeTailoringError(
                "Bullet rewrite source bullets must be from the target bullet's group."
            )
        if bullet_id not in source_ids:
            raise ResumeTailoringError(
                "Bullet rewrite source IDs must include the target bullet ID."
            )

        raw_replacements = raw_edit.get("replacement_bullets")
        if (
            not isinstance(raw_replacements, list)
            or not 1 <= len(raw_replacements) <= MAX_REPLACEMENTS_PER_EDIT
            or not all(isinstance(replacement, str) for replacement in raw_replacements)
        ):
            raise ResumeTailoringError(
                "Bullet rewrite replacements are invalid or exceed the per-edit limit."
            )
        replacements = tuple(raw_replacements)
        if any(
            not replacement.strip()
            or len(replacement) > MAX_REPLACEMENT_BULLET_CHARS
            or "\n" in replacement
            or "\r" in replacement
            for replacement in replacements
        ):
            raise ResumeTailoringError("Bullet rewrite contains an empty or too-long bullet.")
        normalized_replacements = tuple(_normalized_text(value) for value in replacements)
        if len(set(normalized_replacements)) != len(replacements):
            raise ResumeTailoringError("Bullet rewrite contains duplicate replacement bullets.")
        if any(value in seen_replacement_texts for value in normalized_replacements):
            raise ResumeTailoringError(
                "Bullet rewrite contains duplicate replacement text across edits."
            )
        seen_replacement_texts.update(normalized_replacements)
        if len(replacements) == 1 and _normalized_text(replacements[0]) == _normalized_text(
            target.text
        ):
            raise ResumeTailoringError("Bullet rewrite edit is a no-op.")

        replacement_text = "\n".join(replacements)
        replacement_technologies = _technology_terms(replacement_text)
        new_resume_technologies = replacement_technologies - resume_technologies
        if new_resume_technologies:
            raise ResumeTailoringError(
                "Bullet rewrite introduced a technology absent from the source resume."
            )
        cited_text = "\n".join(source.text for source in source_bullets)
        new_cited_technologies = replacement_technologies - _technology_terms(cited_text)
        if new_cited_technologies:
            raise ResumeTailoringError(
                "Bullet rewrite introduced a technology absent from its cited source bullets."
            )
        new_numeric_tokens = _numeric_tokens(replacement_text) - _numeric_tokens(cited_text)
        if new_numeric_tokens:
            raise ResumeTailoringError(
                "Bullet rewrite introduced a numeric token absent from its cited source bullets."
            )
        new_quantity_claims = _numeric_quantity_claims(replacement_text) - (
            _numeric_quantity_claims(cited_text)
        )
        if new_quantity_claims:
            raise ResumeTailoringError(
                "Bullet rewrite changed the unit attached to a cited numeric claim."
            )

        net_new_bullets += len(replacements) - 1
        validated_edits.append(
            ValidatedBulletEdit(
                bullet_id=bullet_id,
                replacement_bullets=replacements,
                source_bullet_ids=source_ids,
            )
        )

    if net_new_bullets > MAX_NET_NEW_BULLETS:
        raise ResumeTailoringError("Bullet rewrite plan exceeds the net-new bullet limit.")
    return ValidatedBulletRewritePlan(edits=tuple(validated_edits), reason_code=reason_code)
