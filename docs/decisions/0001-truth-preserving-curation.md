# ADR 0001: Truth-preserving resume curation

## Status

Accepted - 2026-07-10

## Context

The product should tailor one of three cloud resumes to a job description while retaining the
resume's structure and length. An unconstrained model rewrite could invent qualifications,
inflate responsibility, change dates or metrics, leak more PII than necessary, or produce a
document that no longer renders correctly. Those failures would be especially harmful when the
result is submitted without per-document review.

## Decision

The unattended tailored mode uses OpenAI only to rank opaque IDs for exact skill items already
present in the selected candidate-authored DOCX. Structured output contains evidence quotes and
item permutations. Local code rejects every non-verbatim evidence quote, unknown ID, duplicate,
addition, omission, no-op, or structure change.

The source document is never modified. Curation reuses its separators and formatting-bearing
runs, writes an ignored job-specific copy, reloads it, and compares structural fingerprints.
It then renders source and output with LibreOffice and requires equal page counts. A full model
plan that drifts may be reduced to a smaller model-consistent permutation; if no permutation
retains page count, the output is deleted and the job is skipped. Static mode never calls OpenAI.
Failure never falls back silently.

## Alternatives considered

- **Free-text paragraph rewrites:** closer to conventional resume tailoring, but semantic checks
  cannot reliably prove that responsibility or experience was not inflated. Rejected for
  unattended submission.
- **Blind technology-name replacement:** can create false claims and incoherent experience.
  Rejected.
- **No model; deterministic ordering only:** safest and cheaper, but less capable of interpreting
  nuanced required/preferred language. Kept as a possible future fallback only if explicitly
  selected, not automatic.
- **PDF regeneration:** cannot preserve arbitrary source layout safely in this scope. Rejected.

## Consequences

Tailoring is conservative: it prioritizes existing skills but does not rewrite prose. Some DOCX
layouts will have no parseable safe skill slot and will be skipped. The strong constraint makes
offline testing meaningful, minimizes PII shared with the model, keeps document length constant,
and prevents model output from inventing qualifications by construction.

The supplied GCP sample demonstrated why structural checks alone are insufficient: every tested
skill reorder preserved the semantic fingerprint but expanded the rendered document from two
pages to three. It is therefore safe for static mode and intentionally rejected in tailored mode
until its base page budget is revised.
