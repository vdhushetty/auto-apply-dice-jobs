# Development guide

## Supported environment

Use Python 3.12 and the pinned requirements files. Runtime dependencies remain in
`requirements.txt`; `requirements-dev.txt` adds the single formatter/linter, type checker, and
test runner. Do not introduce a second tool for the same responsibility.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

On Windows activate with `.venv\Scripts\activate`. If Tkinter is not included with Python,
install it through the operating system's Python distribution.
Install LibreOffice for tailored-mode runtime page-count verification.

## Configuration

Tracked defaults are in `config/settings.json`. The GUI writes personal paths and preferences to
ignored `config/settings.local.json`. Secrets stay in ignored `.env`.

- `DICE_USERNAME`, `DICE_PASSWORD`: required for login
- `DICE_AUTOMATION_AUTHORIZED`: must be `true` only with prior written Dice authorization
- `WEB_BROWSER_PATH`: optional Chromium executable override
- `LIBREOFFICE_PATH`: optional `soffice` executable override
- `OPENAI_API_KEY`: tailored mode only
- `OPENAI_MODEL`: optional; defaults to the pinned `gpt-5.5-2026-04-23` snapshot

## Commands

```bash
python run.py
python -m ruff format core/resumes tests scripts
python -m ruff format --check core/resumes tests scripts
python -m ruff check --select E9,F401,F63,F7,F82 .
python -m ruff check core/resumes tests scripts
python -m mypy
python -m pytest
python -m scripts.run_evals
python -m scripts.validate
python -m scripts.audit_resumes --help
```

The legacy GUI/browser modules are not yet fully formatted or typed. CI applies high-signal
undefined-name/syntax linting to the entire repository and full lint/type policy to the new
resume boundary. Expand coverage incrementally when changing legacy modules; do not create an
unrelated whole-repository formatting diff.

## Test strategy

- Selector tests cover provider aliases, required bullet blocks, winner margins, employment
  restrictions, weighted title/description matching, and threshold skips.
- Curator tests use fake Responses clients and adversarial plans; no paid request occurs.
- Document tests generate PII-free replicas of the sample structure, prove exact item and terminal
  punctuation preservation, reject unsafe OOXML, and compare media-aware fingerprints.
- Browser tests prove preview and upload-check side-effect bounds, strict filename verification,
  cancellation, screening-control refusal, exact Dice URLs, and confirmed-only success.
- `evals/resume_matching.jsonl` is the deterministic prompt/model-independent regression set.

Live OpenAI checks are opt-in and must use synthetic content. Live Dice checks require explicit
authorization, an isolated test account, a non-submitting test path where available, and manual
review. They never run in CI.

```bash
RUN_LIVE_OPENAI_SMOKE=1 python -m scripts.live_openai_smoke
RUN_LIVE_OPENAI_SMOKE=1 python -m scripts.live_resume_smoke \
  --aws /path/aws.docx --azure /path/azure.docx --gcp /path/gcp.docx
```

## Build and deployment

Not applicable yet. The app runs from source, has no stable distributable artifact, and has no
deployment target. Add packaging only with an explicit release requirement and platform test
matrix.
