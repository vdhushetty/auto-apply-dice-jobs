# ADR 0002: Reviewed, evidence-grounded bullet tailoring

## Status

Accepted - 2026-08-05. The mandatory-review portion is superseded by
[ADR 0003](0003-explicit-ai-review-policy.md); all evidence and document-integrity requirements
remain accepted.

## Context

Some users want to provide one base DOCX and tailor its experience or project bullets to a job
description. This is materially different from the unattended ID-only skill ordering in ADR 0001.
A free-form rewrite can accidentally introduce a technology, metric, employer, date, duty, or
achievement that the source resume does not support. A structurally valid document is not proof
that its claims are true.

## Decision

Add a separate `ai_bullets` strategy. It uses one user-selected DOCX and the OpenAI Responses API
with strict Structured Outputs. The model receives the job text as untrusted data and only the
candidate-authored editable bullets needed for the task; contact details and unrelated resume
prose are not sent.

The plan may replace at most four original bullets. One replacement may contain a second bullet
only to split or surface facts supported by candidate-authored bullets in the same role or project,
with no more than two net-new bullets per document. Every edit references known source bullet IDs
and exact job evidence. Local validation rejects unknown or duplicate IDs, cross-role evidence,
no-op or oversized text, new recognized technologies absent from the source resume, and numeric
tokens absent from the cited source bullets. The model is explicitly prohibited from inventing
skills, employers, roles, dates, metrics, duties, or achievements.

The source file is never overwritten. The editor changes only targeted bullet text, clones an
existing bullet paragraph when an approved split needs a second point, and preserves paragraph
properties, numbering, styles, non-target text, tables, headers, footers, media, and section
geometry. The generated DOCX must pass bullet-only structural validation and rendered page-count
parity. Any provider, schema, evidence, structural, cache, or layout failure skips the job; there
is no silent fallback.

Because deterministic checks cannot prove semantic equivalence, `ai_bullets` is not permitted to
submit a newly generated file unattended. The exact generated file hash must pass an explicit
local review/approval gate before upload and final submission. A later modification invalidates
that approval.

## Consequences

The strategy can improve job-specific emphasis while retaining the base document's visual design,
but it is intentionally bounded and may decline to edit or apply. It does not replace the static
three-resume strategy or ADR 0001's unattended reorder-only tailored strategy. The review gate is
part of the product contract, not an optional warning.
