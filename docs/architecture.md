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
                                    SKIP       ID-only skill order | whole-resume text plan
                                                                |
                                                local evidence/schema validation
                                                                |
                                            structure-preserving DOCX + page parity
                                                                |
                                      explicit AI review-policy gate
                                         /                      \
                           exact-hash approval                 skip prompt
                         (review_before_apply)              (skip_review)
                                         \                      /
                                          deterministic checks remain
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
the worker. In AI optimization mode it requires a readonly **Review before apply** or **Skip review**
selection, persists the stable policy value locally, and repeats it in the run confirmation.
It also retains a tested Dice session in memory for the current process, validates reuse on a
protected profile route, and exposes secret-free structured progress in Current job, Current
step, Resume, and Last result fields. Worker updates are passed through a thread-safe queue and
executed only by Tk's main loop; browser, logging, and review workers never call Tk directly.

`core/main_script.py` is the external Dice adapter. It extracts the detail-page description,
builds a bounded round-robin pool across search queries, requests side-effect-free resume
evaluations, and ranks only eligible candidates before applying the run limit. It then requests a
prepared resume, restricts automation to Dice Easy Apply, verifies the uploaded filename, and
converts the browser result into `applied`, `already_applied`, `skipped`, or `failed`, plus the
non-submitting `preview_ready` and `upload_verified` outcomes. It refuses visible screening
controls and supports cancellation checks before every consequential click.
Description extraction first uses known visible containers and then Dice's canonical
`JobPosting` JSON-LD. JSON type and size are bounded, HTML is converted to text without
script/style content, and its exact Dice job-detail URL must match the requested/current page.
Redirects to a different job fail closed. After Apply, the adapter accepts only the same job page
or that job identifier's Dice `start-apply`/`wizard` path and selects a file only when exactly one
input is unambiguously labelled as a resume/CV. Browser milestones are emitted as bounded events
containing only job title, step, outcome, profile, and basename.

`core/resumes/selector.py` is pure domain logic. It canonicalizes a version-controlled set of
cloud/data/AI terms, combines weighted title/description coverage with a small lexical signal,
scores every source resume, and enforces the local threshold.
It also parses required bullet sections, requires a configurable winner margin, routes explicit
single-cloud titles, and fails closed on employment restrictions requiring manual review.
For AI optimization mode, `SingleResumeSelector` records the title/full-description score and missing
terms, but does not use either as an initial curation gate. It still stops explicit employment
restrictions for manual review; the bullet validator separately rejects unsupported claims.

`core/resumes/curator.py` is the only OpenAI SDK boundary. It uses the Responses API, Structured
Outputs, `store=False`, bounded SDK retries/timeouts, fixed low reasoning, and a configurable
model. Skill ordering sends job text plus candidate-owned skill IDs/text. AI resume optimization
sends job text plus bounded, safely editable summary, skills, experience, and project items;
contact details, employers, dates, education, and other protected content are not sent.

`core/resumes/bullet_curator.py` owns the AI optimization schema and semantic validator. Plans are
limited to twelve one-for-one paragraph edits, must cite exact source/job evidence, remain within
section-sensitive length budgets, and cannot introduce technologies or quantified claims absent
from cited source items. Experience/project evidence stays within the same role group; summary
and skills may cite supported evidence elsewhere in the resume.

`core/resumes/documents.py` extracts text from DOCX/PDF for selection. Tailored mode detects
delimiter-based skill lists in DOCX skill sections, accepts only exact ID permutations, edits a
copy, reloads it, and compares layout-sensitive structure fingerprints including embedded media,
drawing counts, and legacy objects. Unsupported tracked changes, content controls, text boxes,
and altChunk content are rejected explicitly.

`core/resumes/bullet_documents.py` locates safe summary, skills, experience, and project
paragraphs, applies a validated plan in place to a copy, and verifies exact paragraph count/order,
formatting, protected text, geometry, headers/footers, media, drawings, and objects remain stable.

`core/resumes/layout.py` renders source and output through an isolated LibreOffice profile. A
page-count change or protected section-heading page shift deletes that candidate. The service
retries once, then progressively reduces the validated edit set until a structure-safe version
renders; the application is skipped only if no validated edit can preserve the base layout.

`core/resumes/catalog.py` provides privacy-safe, network-free validation diagnostics for all
three source files.

`core/resumes/service.py` is the application boundary. It validates the mode-specific source set,
selects a source for every job, avoids OpenAI entirely during evaluation/Preview, and caches
generated filenames by job/source/prompt/model fingerprints. AI cache manifests bind the source,
output, job, model, prompt, layout result, and validated edit plan. With `review_before_apply`, a
GUI-thread review callback opens the file and approval binds the exact source/output/job/manifest
hashes. With `skip_review`, only that callback is bypassed; the same generation, cache, evidence,
document, layout, match, and upload-integrity checks run.
OpenAI client construction and document generation remain deferred until an upload mode needs a
file.

## Trust boundaries and data flow

- Dice HTML and job descriptions are untrusted external input.
- Resume files contain sensitive personal data. Only bounded editable summary, skills,
  experience, and project item text required by the strategy is sent; contact details, role
  headings, education, and full document bodies are not sent or logged.
- OpenAI output is untrusted even with a strict schema. Exact evidence and permutations are
  revalidated locally before document changes.
- Browser clicks and file uploads are external side effects. A GUI confirmation and Dice
  authorization attestation are required before the run.
- Tests stop at fakes. CI has no credentials and performs no external side effects.

## Failure model

Expected uncertainty is a skip, not an exception-driven fallback. Configuration errors block the
run. Provider/document errors skip that job. The narrow exception is Verify Upload's explicit,
no-submit source-resume fallback after AI finds no safe non-identical bullet change; it is marked
in structured progress and is unavailable to Submit. Browser errors are failures. Already-applied
jobs are tracked separately and never counted as new submissions.
