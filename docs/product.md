# Product scope

## Goal and users

The product helps an individual job seeker apply selectively to matching Dice roles using one of
three truthful cloud-focused resumes. The primary user owns the Dice account, the three resumes,
and every factual claim in them.

## Primary workflows

1. Configure Dice credentials, authorization attestation, search terms, and a bounded run limit.
2. Select AWS, Azure, and GCP resume variants.
3. Choose static selection or tailored skill prioritization.
4. Start in preview mode, read each full job description, and review low-fit, ambiguous,
   restricted, and supported jobs without clicking Apply.
5. Optionally verify one exact upload without advancing the wizard.
6. Use submit mode only when ready; submit through Dice Easy Apply and record preview-ready,
   upload-verified, confirmed, skipped, already-applied, and failed outcomes separately.

## Functional policy

- Exactly three user-approved variants are required.
- Static mode uploads the highest-scoring original file unchanged.
- Tailored mode selects a DOCX and reorders only exact items in parseable skills lists.
- The relevance threshold is applied before any OpenAI call or Apply click.
- Close winners, explicit clearance/citizenship/sponsorship/W2/onsite restrictions, missing
  required technologies, and visible screening questions require manual review or a skip.
- Tailored output must retain source page count after LibreOffice rendering.
- A local rule always wins over model output.
- Unknown, ambiguous, external, malformed, or unconfirmed states are skipped or failed.

## Success criteria

- Zero applications below the configured threshold in the deterministic eval set.
- Zero accepted model plans that add, remove, duplicate, or rename a candidate skill.
- Zero submissions without a verified intended filename.
- Zero Next/Submit clicks when visible screening controls are present.
- Zero reported successes without a Dice confirmation signal.
- Source resumes remain byte-for-byte untouched.
- Preview performs zero Apply clicks; upload verification performs zero Next/Submit clicks.

## Explicit non-goals

- Generating experience, employers, dates, metrics, certifications, or qualifications.
- Free-text resume rewriting during unattended applications.
- Editing PDFs, scanned resumes, text boxes, or arbitrary complex Word layouts.
- Supporting external employer/ATS apply links.
- Bypassing Dice access controls, terms, bot detection, or account restrictions.
- Packaging, hosting, multi-user accounts, databases, or deployment infrastructure.
