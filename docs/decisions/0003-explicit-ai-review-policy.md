# ADR 0003: Explicit AI bullet review policy

## Status

Accepted - 2026-08-05

## Context

ADR 0002 required a human to inspect and approve every AI-tailored DOCX before upload. The
product owner now needs two deliberate operating modes: keep that review gate, or run the same
bounded and locally validated bullet-tailoring workflow without opening every generated file.
The choice must be visible and settled before automation starts; it must not be inferred from a
missing callback, a cached artifact, or the run mode.

## Decision

Add an explicit `ai_review_policy` setting for the `ai_bullets` resume strategy with two stable
values:

- `review_before_apply`, shown as **Review before apply**, is the default. The exact generated
  file is opened and approval remains bound to the source, output, job, and manifest hashes before
  upload.
- `skip_review`, shown as **Skip review**, bypasses only the human-inspection callback. It does not
  bypass job relevance, source-evidence, schema, technology/number, structure, page-count, cache,
  filename, form, cancellation, or Dice-confirmation checks.

The GUI uses a readonly selector shown only for AI bullet mode. A recognized selection is required
before automation starts. The stable value is persisted in ignored `config/settings.local.json`;
the OpenAI key remains separate in the ignored `.env` file. Every run confirmation identifies the
selected policy. Skip-review confirmations state that only human inspection is bypassed, and
Verify Upload confirmations warn that Dice may leave a draft.

This decision supersedes only ADR 0002's requirement that every AI-bullet output receive human
approval. All other evidence, document-integrity, page-parity, cache-binding, and fail-closed
requirements in ADR 0002 remain in force.

## Consequences

Review before apply remains the safer default and provides a semantic check that deterministic
validators cannot. Skip review supports unattended processing after an explicit user choice, but
the user accepts the residual risk that a factually supported rephrasing may not express the
intended nuance. The run remains bounded and fails closed on every machine-verifiable safety
condition in either policy.
