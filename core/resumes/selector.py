"""Deterministic job-to-resume matching."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import cast

from .models import CloudProfile, CustomProfile, JobPosting, MatchDecision, ResumeVariant

TECH_ALIASES: dict[str, tuple[str, ...]] = {
    "aws": ("aws", "amazon web services"),
    "aws-athena": ("athena", "aws athena"),
    "aws-cloudformation": ("cloudformation",),
    "aws-dynamodb": ("dynamodb",),
    "aws-ec2": ("ec2",),
    "aws-eks": ("eks",),
    "aws-emr": ("emr",),
    "aws-glue": ("aws glue", "glue"),
    "aws-glue-catalog": ("aws glue data catalog", "glue data catalog", "glue catalog"),
    "aws-kinesis": ("kinesis",),
    "aws-lake-formation": ("aws lake formation", "lake formation"),
    "aws-lambda": ("aws lambda", "lambda"),
    "aws-quicksight": ("amazon quicksight", "aws quicksight", "quicksight"),
    "aws-redshift": ("redshift",),
    "aws-s3": ("amazon s3", "aws s3", "s3"),
    "aws-sagemaker": ("sagemaker",),
    "aws-secrets-manager": ("aws secrets manager", "secrets manager"),
    "aws-step-functions": ("step functions",),
    "azure": ("microsoft azure", "azure"),
    "azure-adls-gen2": (
        "adls gen2",
        "azure data lake storage gen2",
        "azure data lake gen2",
        "data lake storage gen2",
    ),
    "azure-aks": ("aks", "azure kubernetes service"),
    "azure-blob-storage": ("azure blob", "blob storage"),
    "azure-cosmos-db": ("cosmos db", "cosmosdb"),
    "azure-data-factory": ("azure data factory", "adf"),
    "azure-devops": ("azure devops",),
    "azure-event-hubs": ("azure event hubs", "event hubs", "eventhub"),
    "azure-fabric": ("microsoft fabric", "azure fabric"),
    "azure-functions": ("azure functions",),
    "azure-key-vault": ("azure key vault", "key vault"),
    "azure-sql": ("azure sql database", "azure sql"),
    "azure-synapse": ("azure synapse", "synapse analytics"),
    "gcp": ("google cloud platform", "google cloud", "gcp"),
    "gcp-bigquery": ("bigquery", "big query"),
    "gcp-cloud-functions": ("google cloud functions", "gcp cloud functions", "cloud functions"),
    "gcp-cloud-logging": (
        "google cloud logging",
        "gcp cloud logging",
        "cloud logging",
        "stackdriver logging",
    ),
    "gcp-cloud-run": ("cloud run",),
    "gcp-cloud-storage": ("google cloud storage", "gcs"),
    "gcp-composer": ("cloud composer",),
    "gcp-dataflow": ("dataflow",),
    "gcp-dataplex": ("google cloud dataplex", "gcp dataplex", "dataplex"),
    "gcp-dataproc": ("dataproc",),
    "gcp-gke": ("gke", "google kubernetes engine"),
    "gcp-looker": ("google looker", "looker studio", "looker"),
    "gcp-pubsub": ("pub/sub", "pubsub", "pub sub"),
    "gcp-secret-manager": ("google secret manager", "gcp secret manager", "secret manager"),
    "gcp-vertex-ai": ("vertex ai",),
    "airflow": ("apache airflow", "airflow"),
    "azure-databricks": ("azure databricks",),
    "c-sharp": ("c sharp", "c#"),
    "databricks": ("databricks",),
    "dax": ("data analysis expressions", "dax"),
    "dbt": ("dbt", "data build tool"),
    "delta-lake": ("delta lake",),
    "docker": ("docker",),
    "dotnet": ("microsoft .net", ".net", "dotnet"),
    "etl": ("etl", "extract transform load"),
    "generative-ai": ("generative ai", "gen ai", "genai"),
    "hadoop": ("apache hadoop", "hadoop"),
    "hdfs": ("hadoop distributed file system", "hdfs"),
    "hive": ("apache hive", "hive"),
    "java": ("java",),
    "kafka": ("apache kafka", "kafka"),
    "kubernetes": ("kubernetes", "k8s"),
    "large-language-models": ("large language models", "large language model", "llms", "llm"),
    "machine-learning": ("machine learning", "ml"),
    "natural-language-processing": ("natural language processing", "nlp"),
    "oracle": ("oracle database", "oracle db", "oracle"),
    "pandas": ("pandas",),
    "power-bi": ("power bi", "powerbi"),
    "pyspark": ("pyspark",),
    "python": ("python",),
    "rag": ("retrieval augmented generation", "retrieval-augmented generation", "rag"),
    "scala": ("scala",),
    "snowflake": ("snowflake",),
    "spark": ("apache spark", "spark"),
    "sql": ("sql",),
    "sql-server": ("microsoft sql server", "sql server"),
    "tableau": ("tableau",),
    "terraform": ("terraform",),
    "t-sql": ("transact-sql", "transact sql", "t-sql", "tsql"),
    "data-analyst": ("data analyst", "analytics analyst"),
    "data-engineer": ("data engineer", "data engineering"),
    "data-scientist": ("data scientist", "data science"),
    "devops-engineer": ("devops engineer", "devops"),
    "machine-learning-engineer": ("machine learning engineer", "ml engineer"),
    "solutions-architect": ("solutions architect", "solution architect"),
}

PROFILE_TERMS: dict[CloudProfile, frozenset[str]] = {
    CloudProfile.AWS: frozenset(
        term for term in TECH_ALIASES if term == "aws" or term.startswith("aws-")
    ),
    CloudProfile.AZURE: frozenset(
        term for term in TECH_ALIASES if term == "azure" or term.startswith("azure-")
    ),
    CloudProfile.GCP: frozenset(
        term for term in TECH_ALIASES if term == "gcp" or term.startswith("gcp-")
    ),
}

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "using",
        "we",
        "will",
        "with",
        "you",
        "your",
        "job",
        "role",
        "work",
        "experience",
        "required",
        "preferred",
        "responsibilities",
        "qualifications",
        "years",
        "team",
        "ability",
        "skills",
        "knowledge",
        "strong",
        "candidate",
        "position",
        "opportunity",
    ]
)
TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9+#.-]{2,}")
REQUIRED_MARKERS = re.compile(
    r"\b(required|requirement|requirements|must have|must-have|mandatory)\b",
    re.IGNORECASE,
)
DEFAULT_MINIMUM_WINNER_MARGIN = 5.0
_REQUIRED_SECTION_HEADING = re.compile(
    r"^\s*(?:requirements?|(?:required|minimum|basic)\s+(?:skills|qualifications|experience)|"
    r"must[-\s]?haves?(?:\s+(?:skills|qualifications|requirements))?|"
    r"mandatory(?:\s+(?:skills|qualifications|requirements))?)"
    r"\s*:?[\t ]*(?P<inline>.*)$",
    re.IGNORECASE,
)
_OTHER_SECTION_HEADING = re.compile(
    r"^\s*(?:preferred(?:\s+(?:skills|qualifications|experience))?|"
    r"nice[-\s]?to[-\s]?have(?:s)?|desired(?:\s+skills)?|responsibilities|duties|"
    r"about(?:\s+(?:the\s+role|us|you))?|benefits|education|overview|job description|"
    r"what\s+you(?:'|\N{RIGHT SINGLE QUOTATION MARK})?ll\s+do)\s*:?\s*$",
    re.IGNORECASE,
)
_BULLET_PREFIX = re.compile(
    r"^\s*(?:[-*\N{BULLET}\N{BLACK SMALL SQUARE}\N{WHITE BULLET}]|\d+[.)])\s*"
)

_CLEARANCE_NEGATION = re.compile(
    r"\b(?:no|without)\s+(?:active\s+)?(?:security\s+)?clearance\b|"
    r"\bclearance\s+(?:is\s+)?not\s+required\b",
    re.IGNORECASE,
)
_MANUAL_REVIEW_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "clearance requirement": (
        re.compile(
            r"\b(?:active\s+)?(?:security|secret|top[-\s]?secret|ts\s*/?\s*sci|"
            r"public trust)\s+clearance\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bclearance\s+(?:is\s+)?(?:required|mandatory|needed)\b", re.I),
        re.compile(
            r"\b(?:must|need(?:s)?\s+to)\s+(?:hold|have|obtain|maintain)\b"
            r"[^.\n]{0,50}\bclearance\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:active\s+)?(?:secret|top[-\s]?secret|ts\s*/?\s*sci|public trust)"
            r"\s+(?:is\s+)?(?:required|mandatory)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:must\s+be\s+)?eligible\s+to\s+obtain\s+(?:a\s+)?"
            r"(?:security\s+clearance|secret|top[-\s]?secret|ts\s*/?\s*sci|public trust)\b",
            re.IGNORECASE,
        ),
    ),
    "citizenship or sponsorship restriction": (
        re.compile(
            r"\bmust\s+be\s+(?:a\s+)?(?:u\.?s\.?|united states)\s+citizens?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:u\.?s\.?|united states)\s+citizens?(?:hip)?\s+"
            r"(?:is\s+)?(?:required|mandatory|only)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bgreen card(?:\s+holders?)?\s+only\b", re.IGNORECASE),
        re.compile(r"\b(?:no|without)\s+(?:visa\s+)?sponsorship\b", re.IGNORECASE),
        re.compile(r"\b(?:will\s+not|cannot|can't|unable\s+to)\s+sponsor\b", re.IGNORECASE),
        re.compile(r"\bsponsorship\s+(?:is\s+)?(?:not\s+available|unavailable)\b", re.IGNORECASE),
        re.compile(r"\bmust\s+be\s+(?:legally\s+)?authorized\s+to\s+work\b", re.IGNORECASE),
    ),
    "W2-only or no-C2C restriction": (
        re.compile(r"\bw[-\s]?2\s+(?:(?:candidates?|profiles?)\s+)?only\b", re.IGNORECASE),
        re.compile(r"\bonly\s+(?:on\s+)?w[-\s]?2\b", re.IGNORECASE),
        re.compile(r"\bno\s+c[-\s]?2[-\s]?c\b", re.IGNORECASE),
        re.compile(r"\bno\s+corp(?:[-\s]?to[-\s]?corp)?\b", re.IGNORECASE),
        re.compile(
            r"\bc[-\s]?2[-\s]?c\s+(?:is\s+)?not\s+(?:accepted|available|allowed)\b",
            re.IGNORECASE,
        ),
    ),
    "onsite or relocation requirement": (
        re.compile(r"\b(?:100\s*%|fully)\s+on[-\s]?site\b|\bno\s+remote\b", re.IGNORECASE),
        re.compile(r"\bmust\s+(?:work|be)\s+on[-\s]?site\b", re.IGNORECASE),
        re.compile(
            r"\bon[-\s]?site\s+(?:only|required|role|position|in\b|from\s+day\s+(?:one|1))",
            re.IGNORECASE,
        ),
        re.compile(r"\bmust\s+be\s+local\b|\blocal\s+candidates?\s+only\b", re.IGNORECASE),
        re.compile(
            r"\brelocation\s+(?:is\s+)?(?:required|mandatory)\b|\bmust\s+relocate\b|"
            r"\bwilling(?:ness)?\s+to\s+relocate\b|\brelocate\s+to\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bhybrid\b[^.\n]{0,60}\b(?:on[-\s]?site|in[-\s]?office)\b", re.IGNORECASE),
        re.compile(
            r"\b(?:on[-\s]?site|in[-\s]?office)\b[^.\n]{0,50}"
            r"\b(?:required|mandatory|\d+\s+days?\s+(?:per|a)\s+week)\b|"
            r"\b\d+\s+days?\s+(?:per|a)\s+week\b[^.\n]{0,50}"
            r"\b(?:on[-\s]?site|in[-\s]?office)\b",
            re.IGNORECASE,
        ),
    ),
}


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias.lower()).replace(r"\ ", r"[\s/-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


_COMPILED_ALIASES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (canonical, _alias_pattern(alias))
    for canonical, aliases in TECH_ALIASES.items()
    for alias in sorted(aliases, key=len, reverse=True)
)


def extract_technology_terms(text: str) -> frozenset[str]:
    """Return canonical technology and role terms found in text."""

    return frozenset(canonical for canonical, pattern in _COMPILED_ALIASES if pattern.search(text))


def extract_lexical_tokens(text: str) -> frozenset[str]:
    """Return significant normalized words for a small lexical signal."""

    return frozenset(
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOPWORDS and not token.isdigit()
    )


def extract_required_technology_terms(description: str) -> frozenset[str]:
    """Extract technology terms from required statements and required bullet sections."""

    required: set[str] = set()
    in_required_section = False
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        required_heading = _REQUIRED_SECTION_HEADING.match(line)
        if required_heading:
            in_required_section = True
            inline = required_heading.group("inline").strip()
            if inline:
                required.update(extract_technology_terms(_BULLET_PREFIX.sub("", inline)))
            continue
        if _OTHER_SECTION_HEADING.match(line):
            in_required_section = False
            continue
        if in_required_section:
            required.update(extract_technology_terms(_BULLET_PREFIX.sub("", line)))

    for segment in re.split(r"(?<=[.!?;])\s+|\n+", description):
        if REQUIRED_MARKERS.search(segment):
            required.update(extract_technology_terms(segment))
    return frozenset(required)


def detect_manual_review_reasons(text: str) -> tuple[str, ...]:
    """Return explicit employment constraints that require a person to review the job."""

    normalized = re.sub(r"\bU\.S\.", "US", text, flags=re.IGNORECASE)
    segments = tuple(
        segment.strip()
        for segment in re.split(r"(?<=[.!?;])\s+|\n+", normalized)
        if segment.strip()
    )
    reasons: list[str] = []
    for reason, patterns in _MANUAL_REVIEW_PATTERNS.items():
        for segment in segments:
            if reason == "clearance requirement" and _CLEARANCE_NEGATION.search(segment):
                continue
            if any(pattern.search(segment) for pattern in patterns):
                reasons.append(reason)
                break
    return tuple(reasons)


def _explicit_title_profile(title_terms: frozenset[str]) -> CloudProfile | None:
    mentioned = [
        profile for profile, terms in PROFILE_TERMS.items() if title_terms.intersection(terms)
    ]
    return mentioned[0] if len(mentioned) == 1 else None


def _weighted_coverage(
    title_terms: frozenset[str], description_terms: frozenset[str], resume_terms: frozenset[str]
) -> float:
    weighted_job_terms: dict[str, float] = {term: 1.0 for term in description_terms}
    for term in title_terms:
        weighted_job_terms[term] = 3.0
    if not weighted_job_terms:
        return 0.0
    matched = sum(weight for term, weight in weighted_job_terms.items() if term in resume_terms)
    return 100.0 * matched / sum(weighted_job_terms.values())


def _lexical_coverage(job: JobPosting, resume_tokens: frozenset[str]) -> float:
    title_tokens = extract_lexical_tokens(job.title)
    description_tokens = extract_lexical_tokens(job.description)
    title_score = (
        100.0 * len(title_tokens & resume_tokens) / len(title_tokens) if title_tokens else 0.0
    )
    description_score = (
        100.0 * len(description_tokens & resume_tokens) / len(description_tokens)
        if description_tokens
        else 0.0
    )
    return 0.65 * title_score + 0.35 * description_score


def _provider_bonus(profile: CloudProfile, job_terms: frozenset[str]) -> float:
    mentioned_profiles = {
        candidate for candidate, terms in PROFILE_TERMS.items() if job_terms.intersection(terms)
    }
    if not mentioned_profiles:
        return 0.0
    return 8.0 if profile in mentioned_profiles else -8.0


class ResumeSelector:
    """Select the most relevant candidate resume using deterministic signals."""

    def __init__(
        self,
        variants: Sequence[ResumeVariant],
        threshold: float,
        minimum_winner_margin: float = DEFAULT_MINIMUM_WINNER_MARGIN,
    ) -> None:
        if len(variants) != len(CloudProfile):
            raise ValueError("Exactly one AWS, Azure, and GCP resume is required.")
        if not 0.0 <= threshold <= 100.0:
            raise ValueError("The relevance threshold must be between 0 and 100.")
        if not 0.0 <= minimum_winner_margin <= 100.0:
            raise ValueError("The minimum winner margin must be between 0 and 100.")
        self._variants = tuple(variants)
        if any(not isinstance(variant.profile, CloudProfile) for variant in self._variants):
            raise ValueError("The three-resume selector accepts cloud profiles only.")
        self._threshold = float(threshold)
        self._minimum_winner_margin = float(minimum_winner_margin)

    def select(self, job: JobPosting) -> MatchDecision:
        title_terms = extract_technology_terms(job.title)
        description_terms = extract_technology_terms(job.description)
        job_terms = title_terms | description_terms
        required_terms = extract_required_technology_terms(job.description)
        explicit_title_profile = _explicit_title_profile(title_terms)
        manual_review_reasons = detect_manual_review_reasons(f"{job.title}\n{job.description}")
        scores: dict[CloudProfile, float] = {}

        for variant in self._variants:
            profile = cast(CloudProfile, variant.profile)
            tech_score = _weighted_coverage(title_terms, description_terms, variant.terms)
            lexical_score = _lexical_coverage(job, variant.lexical_tokens)
            score = 0.80 * tech_score + 0.20 * lexical_score if job_terms else 0.50 * lexical_score
            score += _provider_bonus(profile, job_terms)
            scores[profile] = round(max(0.0, min(100.0, score)), 2)

        def score_key(variant: ResumeVariant) -> tuple[float, int]:
            profile = cast(CloudProfile, variant.profile)
            return scores[profile], -list(CloudProfile).index(profile)

        ranked = sorted(
            self._variants,
            key=score_key,
            reverse=True,
        )
        selected = (
            next(variant for variant in self._variants if variant.profile is explicit_title_profile)
            if explicit_title_profile is not None
            else ranked[0]
        )
        selected_profile = cast(CloudProfile, selected.profile)
        selected_score = scores[selected_profile]
        runner_up_score = max(
            score for profile, score in scores.items() if profile is not selected_profile
        )
        score_margin = round(selected_score - runner_up_score, 2)
        ambiguous = explicit_title_profile is None and score_margin < self._minimum_winner_margin
        matched = sorted(job_terms.intersection(selected.terms))
        missing = sorted(job_terms.difference(selected.terms))
        missing_required = sorted(required_terms.difference(selected.terms))
        return MatchDecision(
            selected_profile=selected_profile,
            selected_path=selected.path,
            score=selected_score,
            threshold=self._threshold,
            eligible=(
                selected_score >= self._threshold
                and not ambiguous
                and not missing_required
                and not manual_review_reasons
            ),
            matched_terms=tuple(matched),
            missing_terms=tuple(missing),
            missing_required_terms=tuple(missing_required),
            ambiguous=ambiguous,
            variant_scores={profile.value: scores[profile] for profile in CloudProfile},
            score_margin=score_margin,
            minimum_winner_margin=self._minimum_winner_margin,
            explicit_title_profile=explicit_title_profile,
            manual_review_reasons=manual_review_reasons,
        )


class SingleResumeSelector:
    """Evaluate one user-provided resume against the title and full job description."""

    def __init__(
        self,
        variant: ResumeVariant,
        threshold: float,
        *,
        allow_tailoring_below_match_threshold: bool = False,
    ) -> None:
        if variant.profile is not CustomProfile.CUSTOM:
            raise ValueError("The single-resume selector requires the custom resume profile.")
        if not 0.0 <= threshold <= 100.0:
            raise ValueError("The relevance threshold must be between 0 and 100.")
        self._variant = variant
        self._threshold = float(threshold)
        self._allow_tailoring_below_match_threshold = allow_tailoring_below_match_threshold

    def select(self, job: JobPosting) -> MatchDecision:
        title_terms = extract_technology_terms(job.title)
        description_terms = extract_technology_terms(job.description)
        job_terms = title_terms | description_terms
        required_terms = extract_required_technology_terms(job.description)
        manual_review_reasons = detect_manual_review_reasons(f"{job.title}\n{job.description}")

        tech_score = _weighted_coverage(title_terms, description_terms, self._variant.terms)
        lexical_score = _lexical_coverage(job, self._variant.lexical_tokens)
        score = 0.80 * tech_score + 0.20 * lexical_score if job_terms else 0.50 * lexical_score
        score = round(max(0.0, min(100.0, score)), 2)
        matched = tuple(sorted(job_terms.intersection(self._variant.terms)))
        missing = tuple(sorted(job_terms.difference(self._variant.terms)))
        missing_required = tuple(sorted(required_terms.difference(self._variant.terms)))

        return MatchDecision(
            selected_profile=CustomProfile.CUSTOM,
            selected_path=self._variant.path,
            score=score,
            threshold=self._threshold,
            eligible=(
                not manual_review_reasons
                and (
                    self._allow_tailoring_below_match_threshold
                    or (score >= self._threshold and not missing_required)
                )
            ),
            matched_terms=matched,
            missing_terms=missing,
            missing_required_terms=missing_required,
            variant_scores={CustomProfile.CUSTOM.value: score},
            manual_review_reasons=manual_review_reasons,
            tailoring_match_gate_bypassed=(
                self._allow_tailoring_below_match_threshold
                and (score < self._threshold or bool(missing_required))
                and not manual_review_reasons
            ),
        )


def all_candidate_terms(variants: Iterable[ResumeVariant]) -> frozenset[str]:
    """Return the evidence-backed skill inventory across all variants."""

    combined: set[str] = set()
    for variant in variants:
        combined.update(variant.terms)
    return frozenset(combined)
