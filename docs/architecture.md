# Architecture

## System flow

```text
Tkinter settings + run mode (preview | verify_upload | submit)
      |
      v
Dice search cards --> Dice detail page --> title + full description
                                             |
                                             v
                                  deterministic ResumeSelector
                                      |                 |
                                below threshold    best AWS/Azure/GCP
                                      |                 |
                                    SKIP          static | tailored
                                                        |
                                       OpenAI ID-only ordering plan
                                                        |
                                       local semantic/schema validation
                                                        |
                                     structure-preserving DOCX copy
                                                        |
                                        rendered page-count parity
                                                        |
Dice Easy Apply <---- exact file path ---- verify input.files[0].name
       |                         |                       |
   preview stops          verify_upload stops       submit continues
                                                        |
                                          Dice confirmation required
```

## Components

`app_tkinter.py` owns interaction and run orchestration. It reads safe defaults plus an ignored
local override, validates resume configuration before starting, and passes immutable values to
the worker.

`core/main_script.py` is the external Dice adapter. It extracts the detail-page description,
requests a prepared resume, restricts automation to Dice Easy Apply, verifies the uploaded
filename, and converts the browser result into `applied`, `already_applied`, `skipped`, or
`failed`, plus the non-submitting `preview_ready` and `upload_verified` outcomes. It refuses
visible screening controls and supports cancellation checks before every consequential click.

`core/resumes/selector.py` is pure domain logic. It canonicalizes a version-controlled set of
cloud/data/AI terms, combines weighted title/description coverage with a small lexical signal,
scores every source resume, and enforces the local threshold.
It also parses required bullet sections, requires a configurable winner margin, routes explicit
single-cloud titles, and fails closed on employment restrictions requiring manual review.

`core/resumes/curator.py` is the only OpenAI boundary. It uses the Responses API, Structured
Outputs, `store=False`, bounded SDK retries/timeouts, and a configurable model. The request
contains the job text and candidate-owned skill IDs/text only; contact and employment sections
are not sent.

`core/resumes/documents.py` extracts text from DOCX/PDF for selection. Tailored mode detects
delimiter-based skill lists in DOCX skill sections, accepts only exact ID permutations, edits a
copy, reloads it, and compares layout-sensitive structure fingerprints including embedded media,
drawing counts, and legacy objects. Unsupported tracked changes, content controls, text boxes,
and altChunk content are rejected explicitly.

`core/resumes/layout.py` renders source and output through an isolated LibreOffice profile. A
page-count change deletes the generated file and skips the application.

`core/resumes/catalog.py` provides privacy-safe, network-free validation diagnostics for all
three source files.

`core/resumes/service.py` is the application boundary. It validates three files once per run,
selects a source for every job, avoids OpenAI entirely in static mode, caches generated filenames
by job/source/prompt/model fingerprints, protects cached outputs with a content manifest, and
returns a fail-closed preparation result. Evaluation is side-effect free; OpenAI construction and
document generation are deferred until upload verification or submission actually needs a file.

## Trust boundaries and data flow

- Dice HTML and job descriptions are untrusted external input.
- Resume files contain sensitive personal data. Only extracted skill-list text is sent for
  curation; full resume prose is not sent or logged.
- OpenAI output is untrusted even with a strict schema. Exact evidence and permutations are
  revalidated locally before document changes.
- Browser clicks and file uploads are external side effects. A GUI confirmation and Dice
  authorization attestation are required before the run.
- Tests stop at fakes. CI has no credentials and performs no external side effects.

## Failure model

Expected uncertainty is a skip, not an exception-driven fallback. Configuration errors block the
run. Provider/document errors skip that job. Browser errors are failures. Already-applied jobs
are tracked separately and never counted as new submissions.
