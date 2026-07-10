"""Application service for selecting and preparing a resume per job."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .curator import PROMPT_VERSION, CurationPlanner, OpenAICurationPlanner, validate_curation_plan
from .documents import (
    SkillSlot,
    collect_skill_slots,
    create_curated_docx,
    extract_resume_text,
    fingerprint_document,
    validate_resume_path,
)
from .layout import DocxLayoutVerifier
from .models import (
    CloudProfile,
    JobPosting,
    MatchDecision,
    PreparedResume,
    ResumeConfigurationError,
    ResumeMode,
    ResumePreparation,
    ResumeTailoringError,
    ResumeVariant,
)
from .selector import (
    DEFAULT_MINIMUM_WINNER_MARGIN,
    ResumeSelector,
    extract_lexical_tokens,
    extract_technology_terms,
)

DEFAULT_THRESHOLD = 35.0
DEFAULT_OUTPUT_DIR = Path(".data/tailored_resumes")
LayoutVerifier = Callable[[Path, Path], None]


class ResumeService:
    """Fail-closed facade used by the Dice browser adapter."""

    def __init__(
        self,
        *,
        mode: ResumeMode,
        paths: Mapping[CloudProfile, str | Path],
        threshold: float = DEFAULT_THRESHOLD,
        minimum_winner_margin: float = DEFAULT_MINIMUM_WINNER_MARGIN,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        planner: CurationPlanner | None = None,
        model: str | None = None,
        safety_identity: str = "",
        layout_verifier: LayoutVerifier | None = None,
    ) -> None:
        self.mode = mode
        self._output_dir = Path(output_dir).expanduser().resolve()
        variants: list[ResumeVariant] = []
        resolved_paths: set[Path] = set()
        content_digests: set[str] = set()
        for profile in CloudProfile:
            path_value = paths.get(profile)
            if not path_value:
                raise ResumeConfigurationError(
                    f"A {profile.value.upper()} resume file is required."
                )
            path = validate_resume_path(path_value, tailored=mode is ResumeMode.TAILORED)
            resolved_paths.add(path)
            content_digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
            text = extract_resume_text(path)
            variants.append(
                ResumeVariant(
                    profile=profile,
                    path=path,
                    text=text,
                    terms=extract_technology_terms(text),
                    lexical_tokens=extract_lexical_tokens(text),
                )
            )
        if len(resolved_paths) != len(CloudProfile):
            raise ResumeConfigurationError("AWS, Azure, and GCP must use three different files.")
        if len(content_digests) != len(CloudProfile):
            raise ResumeConfigurationError(
                "AWS, Azure, and GCP resumes must have distinct file contents."
            )
        self._variants = tuple(variants)
        self._selector = ResumeSelector(
            self._variants,
            threshold,
            minimum_winner_margin=minimum_winner_margin,
        )
        self._planner: CurationPlanner | None
        if mode is ResumeMode.TAILORED:
            self._planner = planner
            self._planner_model = model
            self._safety_identity = safety_identity
            self._layout_verifier: LayoutVerifier | None = (
                layout_verifier if layout_verifier is not None else DocxLayoutVerifier()
            )
        else:
            self._planner = None
            self._planner_model = None
            self._safety_identity = ""
            self._layout_verifier = None

    @classmethod
    def from_settings(
        cls,
        settings: Mapping[str, Any],
        *,
        planner: CurationPlanner | None = None,
        safety_identity: str = "",
        layout_verifier: LayoutVerifier | None = None,
    ) -> ResumeService:
        mode = ResumeMode.parse(str(settings.get("resume_mode", ResumeMode.STATIC.value)))
        raw_paths = settings.get("resume_paths", {})
        if not isinstance(raw_paths, Mapping):
            raise ResumeConfigurationError("resume_paths must be an object.")
        paths = {profile: str(raw_paths.get(profile.value, "")) for profile in CloudProfile}
        threshold = float(settings.get("minimum_match_score", DEFAULT_THRESHOLD))
        minimum_winner_margin = float(
            settings.get("minimum_winner_margin", DEFAULT_MINIMUM_WINNER_MARGIN)
        )
        output_dir = str(settings.get("tailored_resume_output_dir", DEFAULT_OUTPUT_DIR))
        model = str(settings.get("openai_model", "")).strip() or None
        return cls(
            mode=mode,
            paths=paths,
            threshold=threshold,
            minimum_winner_margin=minimum_winner_margin,
            output_dir=output_dir,
            planner=planner,
            model=model,
            safety_identity=safety_identity,
            layout_verifier=layout_verifier,
        )

    def evaluate(self, job: JobPosting) -> ResumePreparation:
        """Evaluate local fit without generating or modifying a resume."""

        decision = self._selector.select(job)
        return ResumePreparation(
            eligible=decision.eligible,
            reason=decision.reason,
            decision=decision,
        )

    def prepare_selected(self, job: JobPosting, decision: MatchDecision) -> ResumePreparation:
        """Prepare a previously evaluated decision without re-running selection."""

        approved_paths = {variant.path for variant in self._variants}
        if decision.selected_path not in approved_paths:
            return ResumePreparation(
                eligible=False,
                reason="Resume decision referenced an unapproved source file.",
                decision=decision,
            )
        if not decision.eligible:
            return ResumePreparation(
                eligible=False,
                reason=decision.reason,
                decision=decision,
            )
        if self.mode is ResumeMode.STATIC:
            return ResumePreparation(
                eligible=True,
                reason=decision.reason,
                decision=decision,
                prepared=PreparedResume(
                    path=decision.selected_path,
                    decision=decision,
                    tailored=False,
                ),
            )

        try:
            prepared_path = self._prepare_tailored(job, decision.selected_path)
        except ResumeTailoringError as exc:
            return ResumePreparation(
                eligible=False,
                reason=str(exc),
                decision=decision,
            )
        return ResumePreparation(
            eligible=True,
            reason=decision.reason,
            decision=decision,
            prepared=PreparedResume(
                path=prepared_path,
                decision=decision,
                tailored=True,
            ),
        )

    def prepare(self, job: JobPosting) -> ResumePreparation:
        """Select, gate, and optionally curate a resume for one job."""

        evaluation = self.evaluate(job)
        if not evaluation.eligible or evaluation.decision is None:
            return evaluation
        return self.prepare_selected(job, evaluation.decision)

    def _prepare_tailored(self, job: JobPosting, source_path: Path) -> Path:
        from docx import Document

        if self._planner is None:
            self._planner = OpenAICurationPlanner(
                model=self._planner_model,
                safety_identity=self._safety_identity,
            )
        document = Document(str(source_path))
        slots = collect_skill_slots(document)
        if not slots:
            raise ResumeTailoringError(
                "No safely editable skill list was found in the selected DOCX."
            )
        output_path = self._output_path(job, source_path, self._planner.model)
        if output_path.exists() and self._cached_output_is_valid(source_path, output_path):
            return output_path
        output_path.unlink(missing_ok=True)
        self._manifest_path(output_path).unlink(missing_ok=True)
        raw_plan = self._planner.plan(job, slots)
        plan = validate_curation_plan(raw_plan, job, slots)
        changed_orders = {
            slot_id: order
            for slot_id, order in plan.slot_orders.items()
            if order != next(slot for slot in slots if slot.slot_id == slot_id).original_order
        }
        candidates = self._candidate_orders(slots, changed_orders)

        last_layout_error: ResumeTailoringError | None = None
        for candidate_orders in candidates:
            try:
                create_curated_docx(source_path, output_path, candidate_orders)
                if self._layout_verifier is None:
                    raise ResumeTailoringError("Tailored mode has no layout verifier.")
                self._layout_verifier(source_path, output_path)
                self._write_cache_manifest(source_path, output_path)
                return output_path
            except ResumeTailoringError as exc:
                output_path.unlink(missing_ok=True)
                self._manifest_path(output_path).unlink(missing_ok=True)
                last_layout_error = exc
                if "changed the rendered page count" not in str(exc):
                    raise
        if last_layout_error is not None:
            raise last_layout_error
        raise ResumeTailoringError("No safe tailored resume could be generated.")

    @staticmethod
    def _candidate_orders(
        slots: tuple[SkillSlot, ...],
        changed_orders: dict[str, tuple[str, ...]],
    ) -> tuple[dict[str, tuple[str, ...]], ...]:
        """Try the model plan, then smaller model-consistent page-safe edits."""

        originals = {slot.slot_id: slot.original_order for slot in slots}
        candidates: list[dict[str, tuple[str, ...]]] = []
        seen: set[tuple[tuple[str, tuple[str, ...]], ...]] = set()

        def add(candidate: dict[str, tuple[str, ...]]) -> None:
            key = tuple(sorted(candidate.items()))
            if candidate and key not in seen:
                candidates.append(candidate)
                seen.add(key)

        add(changed_orders)
        for slot_id, target_order in changed_orders.items():
            add({slot_id: target_order})
            original_order = originals[slot_id]
            target_positions = {item_id: index for index, item_id in enumerate(target_order)}
            for index in range(len(original_order) - 1):
                left = original_order[index]
                right = original_order[index + 1]
                if target_positions[left] <= target_positions[right]:
                    continue
                adjacent_order = list(original_order)
                adjacent_order[index], adjacent_order[index + 1] = right, left
                add({slot_id: tuple(adjacent_order)})
        return tuple(candidates)

    @staticmethod
    def _manifest_path(output_path: Path) -> Path:
        return output_path.with_suffix(f"{output_path.suffix}.manifest.json")

    @staticmethod
    def _file_digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _cached_output_is_valid(self, source_path: Path, output_path: Path) -> bool:
        from docx import Document

        manifest_path = self._manifest_path(output_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("layout_verified") is not True:
                return False
            if manifest.get("source_sha256") != self._file_digest(source_path):
                return False
            if manifest.get("output_sha256") != self._file_digest(output_path):
                return False
            validate_resume_path(output_path, tailored=True)
            source_document = Document(str(source_path))
            cached_document = Document(str(output_path))
            if fingerprint_document(cached_document) != fingerprint_document(source_document):
                return False
            return Counter(extract_resume_text(source_path)) == Counter(
                extract_resume_text(output_path)
            )
        except Exception:
            return False

    def _write_cache_manifest(self, source_path: Path, output_path: Path) -> None:
        manifest_path = self._manifest_path(output_path)
        manifest_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        payload = {
            "layout_verified": True,
            "source_sha256": self._file_digest(source_path),
            "output_sha256": self._file_digest(output_path),
            "prompt_version": PROMPT_VERSION,
            "model": self._planner.model if self._planner is not None else "",
        }
        temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        if temporary_path.stat().st_size == 0:
            raise ResumeTailoringError("Tailored resume cache manifest could not be written.")
        if os.name != "nt":
            os.chmod(temporary_path, 0o600)
        temporary_path.replace(manifest_path)

    def _output_path(self, job: JobPosting, source_path: Path, model: str) -> Path:
        title_slug = re.sub(r"[^a-z0-9]+", "-", job.title.lower()).strip("-")[:60]
        source_stat = source_path.stat()
        cache_material = "|".join(
            (
                job.url,
                hashlib.sha256(job.description.encode()).hexdigest(),
                str(source_path),
                str(source_stat.st_mtime_ns),
                str(source_stat.st_size),
                PROMPT_VERSION,
                model,
            )
        )
        digest = hashlib.sha256(cache_material.encode()).hexdigest()[:12]
        return self._output_dir / f"{title_slug or 'dice-job'}-{digest}.docx"
