"""Rendered page-count verification for tailored DOCX files."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import ResumeTailoringError

SOFFICE_TIMEOUT_SECONDS = 60


def _find_soffice() -> Path | None:
    configured = os.getenv("LIBREOFFICE_PATH", "").strip()
    program_files = os.getenv("PROGRAMFILES", "")
    program_files_x86 = os.getenv("PROGRAMFILES(X86)", "")
    candidates = [
        configured,
        shutil.which("soffice") or "",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/Applications/LibreOfficeDev.app/Contents/MacOS/soffice",
        str(Path(program_files) / "LibreOffice/program/soffice.exe") if program_files else "",
        str(Path(program_files_x86) / "LibreOffice/program/soffice.exe")
        if program_files_x86
        else "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def _rendered_page_count(path: Path, soffice: Path) -> int:
    """Render one DOCX in an isolated profile and count its PDF pages."""

    from pypdf import PdfReader

    try:
        with tempfile.TemporaryDirectory(prefix="dice-resume-layout-") as temp_value:
            temp_dir = Path(temp_value)
            output_dir = temp_dir / "output"
            profile_dir = temp_dir / "profile"
            home_dir = temp_dir / "home"
            output_dir.mkdir()
            profile_dir.mkdir()
            home_dir.mkdir()
            environment = os.environ.copy()
            environment["HOME"] = str(home_dir)
            environment["TMPDIR"] = str(temp_dir)
            completed = subprocess.run(
                [
                    str(soffice),
                    "--headless",
                    f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(path),
                ],
                check=False,
                capture_output=True,
                env=environment,
                text=True,
                timeout=SOFFICE_TIMEOUT_SECONDS,
            )
            rendered_pdf = output_dir / f"{path.stem}.pdf"
            if completed.returncode != 0 or not rendered_pdf.is_file():
                raise ResumeTailoringError(
                    "Tailored resume layout verification could not render the DOCX."
                )
            page_count = len(PdfReader(str(rendered_pdf)).pages)
            if page_count < 1:
                raise ResumeTailoringError("Tailored resume layout verification produced no pages.")
            return page_count
    except subprocess.TimeoutExpired as exc:
        raise ResumeTailoringError("Tailored resume layout verification timed out.") from exc
    except ResumeTailoringError:
        raise
    except Exception as exc:
        raise ResumeTailoringError("Tailored resume layout verification failed.") from exc


class DocxLayoutVerifier:
    """Fail closed unless source and tailored DOCX render to the same page count."""

    def __init__(self, soffice: str | Path | None = None) -> None:
        self._soffice = Path(soffice).resolve() if soffice else _find_soffice()
        self._source_page_counts: dict[tuple[Path, int, int], int] = {}

    def __call__(self, source_path: Path, output_path: Path) -> None:
        if self._soffice is None:
            raise ResumeTailoringError(
                "Tailored mode requires LibreOffice for page-count verification. "
                "Install LibreOffice or use static mode."
            )
        source_stat = source_path.stat()
        source_key = (source_path.resolve(), source_stat.st_mtime_ns, source_stat.st_size)
        source_pages = self._source_page_counts.get(source_key)
        if source_pages is None:
            source_pages = _rendered_page_count(source_path, self._soffice)
            self._source_page_counts[source_key] = source_pages
        output_pages = _rendered_page_count(output_path, self._soffice)
        if output_pages != source_pages:
            raise ResumeTailoringError(
                "Tailored resume changed the rendered page count and was discarded."
            )
