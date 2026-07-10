from pathlib import Path

import pytest

import core.resumes.layout as layout
from core.resumes.layout import DocxLayoutVerifier
from core.resumes.models import ResumeTailoringError


def test_layout_verifier_accepts_matching_page_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    source.touch()
    output.touch()
    monkeypatch.setattr(layout, "_rendered_page_count", lambda path, soffice: 2)

    DocxLayoutVerifier(soffice=source)(source, output)


def test_layout_verifier_rejects_page_count_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    counts = {source: 2, output: 3}
    monkeypatch.setattr(
        layout,
        "_rendered_page_count",
        lambda path, soffice: counts[path],
    )

    with pytest.raises(ResumeTailoringError, match="page count"):
        DocxLayoutVerifier(soffice=source)(source, output)


def test_layout_verifier_requires_libreoffice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "_find_soffice", lambda: None)
    verifier = DocxLayoutVerifier()

    with pytest.raises(ResumeTailoringError, match="LibreOffice"):
        verifier(Path("source.docx"), Path("output.docx"))
