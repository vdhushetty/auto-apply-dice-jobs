# Sample resume validation

Validation was performed locally on 2026-07-10 using the user-provided sample folder. Personal
files and extracted resume content were not copied into the repository, logs, fixtures, or evals.
The committed tests use generated, PII-free structural replicas.

## Compatibility results

| Profile | Format | Recognized terms | Safe skill slots | Skill items | Result |
|---|---:|---:|---:|---:|---|
| AWS | DOCX | 33 | 4 | 46 | Tailored-ready; live synthetic curation retained two pages |
| Azure | DOCX | 30 | 4 | 50 | Tailored-ready; live synthetic curation retained two pages |
| GCP | DOCX | 32 | 4 | 45 | Parseable, but synthetic curation was rejected for page-count drift |
| AWS/Azure/GCP | PDF | 26-33 | 0 | 0 | Text-extractable and supported for static selection only |

All inspected DOCX and PDF files rendered cleanly as two A4 pages. The DOCX files use ordinary
body paragraphs plus a contact/badge table. The audit found no tracked changes, content controls,
text boxes, or altChunk content. Embedded badge media and drawing/object counts are now part of
the immutable document fingerprint.

A ten-job sanitized matrix was evaluated against the actual DOCX text. Six clear AWS, Azure, and
GCP jobs selected the intended profile. Four risky cases were skipped as designed: a cloud-neutral
near tie, unsupported required C#/.NET/Kubernetes, an explicit clearance requirement, and a
multi-cloud result below the configured five-point winner margin.

## GCP page-budget finding

The GCP source is already at its two-page boundary. The live model plan, every model-consistent
minimal candidate, and all 41 possible adjacent single-slot swaps rendered to three pages. The
application therefore deletes the generated file and skips the application rather than violating
the configured structure and length guarantee.

Static GCP selection remains supported. To enable tailored GCP output, provide a slightly shorter
GCP DOCX base or intentionally revise its layout, then rerun the audit and live smoke test.

## Commands

Privacy-safe local inspection:

```bash
python -m scripts.audit_resumes --aws /path/aws.docx --azure /path/azure.docx \
  --gcp /path/gcp.docx
```

Opt-in paid OpenAI and rendered-layout smoke test:

```bash
RUN_LIVE_OPENAI_SMOKE=1 python -m scripts.live_resume_smoke \
  --aws /path/aws.docx --azure /path/azure.docx --gcp /path/gcp.docx
```

The live smoke uses synthetic job descriptions. It sends candidate-authored skill lists only and
does not send contact details, employment prose, source paths, or files.
