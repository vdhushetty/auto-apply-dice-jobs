# Dice Resume-Aware Apply Bot

This repository contains an early-stage Python desktop application that searches Dice,
filters jobs, chooses the most relevant AWS/Azure/GCP resume, and supports Dice Easy Apply.
It is a maintained prototype, not a production service or a supported Dice integration.

The default run mode is **preview**. It reads job details and reports fit decisions without
clicking Apply.

Live automation is disabled unless `DICE_AUTOMATION_AUTHORIZED=true`. Set that flag only
after obtaining Dice's prior written authorization. Dice's current terms restrict automated
navigation and retrieval, inaccurate resume content, and keyword stuffing. See the
[Dice Terms and Conditions](https://www.dice.com/about/terms-and-conditions/).

## Resume modes

- **Static:** score all three resumes against the full job title and description, skip jobs
  below the configured threshold, and upload the best source file unchanged. Static mode
  accepts DOCX or text-based PDF resumes.
- **Tailored:** select the best DOCX, ask OpenAI for an ID-only ordering plan, validate that
  every returned ID is an exact permutation of candidate-authored skill items, and create a
  job-specific DOCX. The model cannot add, delete, rename, or rewrite skills or claims. The
  generated file must render to the same page count as its source or it is deleted and skipped.

Both modes require exactly three user-approved files labelled AWS, Azure, and GCP. No personal
resume files are included in the repository.

## Current safety behavior

The application skips instead of submitting when any of these checks fail:

- the job description cannot be read;
- the best resume score is below the configured threshold;
- tailored output is refused, malformed, unchanged, or structurally unsafe;
- the posting leaves Dice instead of entering Dice Easy Apply;
- the intended filename cannot be verified in a file input; or
- Dice does not visibly confirm submission.

Each run also requires an explicit confirmation in the GUI. Resume contents, job descriptions,
and API keys are not written to application logs.

Three side-effect levels are available:

- **Preview:** inspect, score, and classify Easy Apply jobs; never click Apply.
- **Verify upload:** one-job maximum; select and verify the exact resume file, then stop before
  Next or Submit. Dice may retain a draft.
- **Submit:** upload and submit only after all fit, upload, form, and confirmation checks pass.

## Prerequisites

- Python 3.12
- macOS, Windows, or Linux with Tkinter
- Brave or Google Chrome; browser launching currently uses ChromeDriver
- LibreOffice/`soffice` for tailored-mode rendered page-count verification
- A Dice account and prior written authorization from Dice for automated access
- An OpenAI API key only for tailored mode

## Setup

```bash
git clone https://github.com/yuva-raja-reddy/auto-apply-dice-jobs.git
cd auto-apply-dice-jobs
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally. Never commit it:

```dotenv
DICE_USERNAME=
DICE_PASSWORD=
DICE_AUTOMATION_AUTHORIZED=false
WEB_BROWSER_PATH=
LIBREOFFICE_PATH=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5-2026-04-23
```

`OPENAI_API_KEY` is unnecessary in static mode. The default is a pinned GPT-5.5 snapshot because
GPT-5.6 was still unavailable to this project's API account during initialization. Change
`OPENAI_MODEL` only after running the evaluation set.

## Run locally

```bash
python run.py
```

In **Settings**:

1. Enter and test Dice credentials.
2. Leave the run mode on `preview` for the first run.
3. Choose `static` or `tailored`.
4. Select and validate one AWS, Azure, and GCP resume.
5. Choose the minimum match score, winner margin, and a small job limit.
6. Save settings. Personal paths are written atomically to ignored
   `config/settings.local.json` with local-only permissions.
7. Start the bot and review the mode-specific confirmation.

Generated tailored files are kept under ignored `.data/tailored_resumes/`. Consolidated,
run-scoped Excel and JSON reports are written under ignored `.data/runs/`.

## Development and validation

Install development tools in the same virtual environment:

```bash
python -m pip install -r requirements-dev.txt
python -m scripts.validate
```

The full command runs dependency checks, formatting checks, high-signal linting over the legacy
application, full linting and strict type checks for the new resume domain, offline tests,
deterministic matching evals, and Python bytecode compilation.

Individual commands:

```bash
python -m ruff format core/resumes tests scripts
python -m ruff format --check core/resumes tests scripts
python -m ruff check --select E9,F401,F63,F7,F82 .
python -m ruff check core/resumes tests scripts
python -m mypy
python -m pytest
python -m scripts.run_evals
python -m compileall -q app_tkinter.py core run.py
```

There is no packaging/build command yet: this prototype is run from source and has no defined
deployment artifact.

## Repository map

- `app_tkinter.py` - GUI, local settings, run confirmation, and orchestration
- `core/main_script.py` - Dice/Chrome adapter and fail-closed Easy Apply flow
- `core/resumes/` - matching, document validation, OpenAI boundary, and resume service
- `config/settings.json` - safe tracked defaults
- `config/settings.local.json` - ignored personal settings created by the GUI
- `evals/` - credential-free matching cases
- `tests/` - offline unit and workflow tests; no live Dice/OpenAI calls
- `scripts/validate.py` - canonical full validation command
- `scripts/audit_resumes.py` - privacy-safe offline compatibility and match preview
- `scripts/live_resume_smoke.py` - opt-in synthetic OpenAI plus rendered-layout smoke test

Architecture, development, and risk details live in:

- [Product scope](docs/product.md)
- [Architecture](docs/architecture.md)
- [Development guide](docs/development.md)
- [Security and privacy](docs/security.md)
- [Sample resume validation](docs/sample-validation.md)
- [Curation safety decision](docs/decisions/0001-truth-preserving-curation.md)

## Known limitations

- Dice selectors and wizard behavior can change. No live Dice submission was executed during
  repository initialization or sample validation.
- Tailored mode safely reorders existing skill items; it intentionally does not rewrite prose,
  employment history, dates, metrics, education, or certifications.
- Tailored mode requires parseable delimiter-based skill lists in DOCX files. Complex text boxes,
  content controls, tracked changes, or scanned documents are not supported.
- The matcher uses a version-controlled technology taxonomy and a lexical signal. The eval set is
  a regression baseline, not proof of universal ranking quality.
- PDF is selection/upload-only; safe structure-preserving PDF editing is out of scope.
- Selenium Manager/browser resolution has not been live-tested across the supported platforms.
- The supplied GCP sample is safe for static selection but currently rejects every tailored
  reorder because it would grow from two rendered pages to three.
