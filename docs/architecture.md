# Architecture

## System flow

```text
Tkinter settings + run mode (preview | verify_upload | submit)
      |
      v
Dice search cards --> Dice detail page --> title + full description
                                             |
                                             v
                              deterministic selector (three variants | one base)
                                      |                         |
                                below threshold       static | tailored | ai_bullets
                                      |                         |
                                    SKIP       ID-only skill order | bounded bullet plan
                                                                |
                                                local evidence/schema validation
                                                                |
                                            structure-preserving DOCX + page parity
                                                                |
                                              exact-hash human review (AI bullets)
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
builds a bounded round-robin pool across search queries, requests side-effect-free resume
evaluations, and ranks only eligible candidates before applying the run limit. It then requests a
prepared resume, restricts automation to Dice Easy Apply, verifies the uploaded filename, and
converts the browser result into `applied`, `already_applied`, `skipped`, or `failed`, plus the
non-submitting `preview_ready` and `upload_verified` outcomes. It refuses visible screening
controls and supports cancellation checks before every consequential click.

`core/resumes/selector.py` is pure domain logic. It canonicalizes a version-controlled set of
cloud/data/AI terms, combines weighted title/description coverage with a small lexical signal,
scores every source resume, and enforces the local threshold.
It also parses required bullet sections, requires a configurable winner margin, routes explicit
single-cloud titles, and fails closed on employment restrictions requiring manual review.
For AI bullet mode, `SingleResumeSelector` applies the same title/full-description threshold,
required-term, and restriction gates to one custom profile without a three-way winner margin.

`core/resumes/curator.py` is the only OpenAI SDK boundary. It uses the Responses API, Structured
Outputs, `store=False`, bounded SDK retries/timeouts, fixed low reasoning, and a configurable
model. Skill ordering sends job text plus candidate-owned skill IDs/text. AI bullet tailoring
sends job text plus bounded editable experience bullets; contact details and protected sections
are not sent.

`core/resumes/bullet_curator.py` owns the AI-bullet schema and semantic validator. Plans are
limited to four target bullets and two net-new bullets, must cite exact source/job evidence, and
cannot introduce technologies or quantified claims absent from the cited same-role bullets.

`core/resumes/documents.py` extracts text from DOCX/PDF for selection. Tailored mode detects
delimiter-based skill lists in DOCX skill sections, accepts only exact ID permutations, edits a
copy, reloads it, and compares layout-sensitive structure fingerprints including embedded media,
drawing counts, and legacy objects. Unsupported tracked changes, content controls, text boxes,
and altChunk content are rejected explicitly.

`core/resumes/bullet_documents.py` locates supported experience bullets, applies a validated plan
to a copy, and verifies that only approved bullet paragraphs changed while protected text,
styles, geometry, headers/footers, media, drawings, and objects remain stable.

`core/resumes/layout.py` renders source and output through an isolated LibreOffice profile. A
page-count change deletes the generated file and skips the application.

`core/resumes/catalog.py` provides privacy-safe, network-free validation diagnostics for all
three source files.

`core/resumes/service.py` is the application boundary. It validates the mode-specific source set,
selects a source for every job, avoids OpenAI entirely during evaluation/Preview, and caches
generated filenames by job/source/prompt/model fingerprints. AI cache manifests bind the source,
output, job, model, prompt, layout result, and validated edit plan. Before upload, a GUI-thread
review callback opens the file; approval binds the exact source/output/job/manifest hashes.
OpenAI client construction and document generation remain deferred until an upload mode needs a
file.

## Trust boundaries and data flow

- Dice HTML and job descriptions are untrusted external input.
- Resume files contain sensitive personal data. Only extracted skill-list text or editable
  experience bullets required by the chosen strategy are sent; full resume prose is not sent or
  logged.
- OpenAI output is untrusted even with a strict schema. Exact evidence and permutations are
  revalidated locally before document changes.
- Browser clicks and file uploads are external side effects. A GUI confirmation and Dice
  authorization attestation are required before the run.
- Tests stop at fakes. CI has no credentials and performs no external side effects.

## Failure model

Expected uncertainty is a skip, not an exception-driven fallback. Configuration errors block the
run. Provider/document errors skip that job. Browser errors are failures. Already-applied jobs
are tracked separately and never counted as new submissions.
