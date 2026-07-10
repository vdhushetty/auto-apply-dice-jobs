# Repository instructions

## Purpose and constraints

This is a Python 3.12 Tkinter/Selenium prototype for resume-aware Dice Easy Apply. Every
application must use the full job description, pass the relevance threshold, use one of the
user's three factual AWS/Azure/GCP resumes, verify the intended upload, and receive Dice's
submission confirmation. Fail closed on uncertainty. Never invent candidate qualifications.

Live Dice automation is allowed only when `DICE_AUTOMATION_AUTHORIZED=true` represents prior
written authorization from Dice. Never bypass that gate.

## Repository map and boundaries

- `app_tkinter.py`: UI and orchestration. Capture Tk values before starting worker threads.
- `core/main_script.py`: Dice/browser adapter only. It consumes resume decisions; it must not
  choose or rewrite a resume.
- `core/resumes/selector.py`: deterministic, network-free matching policy and taxonomy.
- `core/resumes/curator.py`: sole OpenAI boundary and structured-output schema.
- `core/resumes/documents.py`: resume parsing and structure-preserving DOCX operations.
- `core/resumes/layout.py`: mandatory rendered page-count parity for tailored output.
- `core/resumes/catalog.py`: network-free compatibility diagnostics.
- `core/resumes/service.py`: application-level select/gate/curate flow.
- `config/settings.json`: safe defaults. Personal paths belong in ignored
  `config/settings.local.json`.
- `tests/`: offline tests. `evals/`: deterministic matching regression cases.

Product scope is in `docs/product.md`; architecture and trust boundaries are in
`docs/architecture.md`; security rules are in `docs/security.md`. The curation safety decision is
recorded in `docs/decisions/0001-truth-preserving-curation.md`.

## Canonical commands

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
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

There is no packaging or deployment command. Do not add one until a real artifact/target exists.

## Coding and testing rules

- New resume-domain code must be typed, formatted by Ruff, and free of implicit network calls.
- Keep matching deterministic. The model cannot override a local relevance skip.
- Treat job descriptions and model responses as untrusted data. Validate all returned IDs and
  exact evidence quotes locally.
- Tailored mode may only reorder exact candidate-authored skill items. Do not add free-text
  rewriting to unattended submission.
- Never overwrite source resumes. Generated files go under ignored `.data/`.
- Preview must never click Apply. Upload verification must never click Next or Submit and is
  limited to one job. Submit must refuse visible screening controls.
- Tailored files must pass both semantic fingerprints and rendered page-count parity. Do not
  weaken the layout gate to increase application volume.
- Static mode must never call OpenAI. AI/provider failures must skip, never fall back silently.
- Unit tests must not use live Dice, browsers, credentials, or paid model calls. Inject fakes.
- Bug fixes require a regression test. Prompt/model changes require updated eval coverage.
- Browser submission tests must prove: mismatches never reach Apply, missing uploads never reach
  Submit, unconfirmed submissions are failures, and original navigation is restored.

## Security and data rules

- Never print or commit `.env`, API keys, Dice credentials, resumes, job-description bodies, or
  personal file paths.
- Keep `.env`, `config/settings.local.json`, reports, logs, and `.data/` ignored.
- Do not disable browser sandbox/web security or add automation-evasion behavior.
- Do not weaken upload or confirmation checks to accommodate a changed Dice UI; update selectors
  with tests and retain fail-closed behavior.
- Do not run live Dice/OpenAI integration tests in CI. Live checks are opt-in and use synthetic,
  non-personal input where possible.
- Do not commit, push, deploy, or publish unless explicitly asked.

## Definition of done

The requested behavior is implemented; relevant tests/evals are updated; `python -m
scripts.validate` passes; documentation matches runtime behavior; no secret/PII or unrelated
change is present; and the final diff has been reviewed.
