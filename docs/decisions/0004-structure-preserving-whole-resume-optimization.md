# ADR 0004: Structure-preserving whole-resume optimization

## Status

Accepted.

## Context

The first AI mode could rewrite only four experience bullets and could split two of them into
additional paragraphs. That provided limited job alignment and made "preserve the base resume
structure" harder to state precisely. The product needs to optimize all relevant resume content
for each full Dice job description while retaining the user's exact template.

## Decision

AI mode exposes only safely editable summary, skills, experience, and project paragraphs. OpenAI
returns a strict, ID-based plan with at most twelve one-for-one text replacements. It may use
job-description vocabulary only where cited candidate-authored resume items support the claim.

The local validator requires exact job evidence, known target/source IDs, the target among its
sources, source-supported technologies and numeric claims, unique nonempty replacements, and a
section-sensitive character budget. Experience and project edits can cite only their own role
group; summary and skills edits may cite supported items elsewhere in the resume.

The document layer permits no paragraph insertion, deletion, relocation, or style change. It
proves the paragraph count and order are identical, all non-target XML is unchanged, all package
parts and relationships remain present, and only authorized text nodes differ. LibreOffice
rendering must also preserve page count and protected section-heading page positions. If a full
validated plan changes pagination, the service requests one conservative repair and then
progressively removes the highest-layout-pressure edits until a nonempty safe subset fits.

## Consequences

The optimizer can align summary, skills, experience, and projects to a job rather than changing a
small fixed set of bullets. It still cannot manufacture qualifications or guarantee a rewrite for
a job whose requirements have no source evidence. Complex text boxes, content controls, fields,
and mixed-format paragraphs remain protected rather than exposed to the model.
