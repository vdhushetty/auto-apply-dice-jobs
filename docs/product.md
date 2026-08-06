# Product scope

## Goal and users

The product helps an individual job seeker apply selectively to matching Dice roles using either
three truthful cloud-focused resumes or one user-provided base resume. The primary user owns the
Dice account, every source resume, and every factual claim in them.

## Primary workflows

1. Configure Dice credentials, authorization attestation, search terms, and a bounded run limit.
2. Select AWS/Azure/GCP variants, or select one base DOCX for AI bullet tailoring.
3. Choose static selection, tailored skill prioritization, or AI bullet tailoring. For AI
   bullets, explicitly choose **Review before apply** or **Skip review** before starting.
4. Start in preview mode. Build a bounded round-robin sample across the configured searches,
   read each sampled full job description, rank resume-eligible jobs by match score, and inspect
   the highest-fit jobs without clicking Apply.
5. Optionally verify one exact upload without advancing the wizard.
6. Use submit mode only when ready; submit through Dice Easy Apply and record preview-ready,
   upload-verified, confirmed, skipped, already-applied, and failed outcomes separately.

## Functional policy

- Static and tailored modes require exactly three user-approved variants. AI bullet mode requires
  exactly one user-approved DOCX.
- Full-description ranking uses a deterministic candidate pool of four times the run limit, with
  at least one candidate slot per nonempty search bucket, before the application cap is applied.
- Static mode uploads the highest-scoring original file unchanged.
- Tailored mode selects a DOCX and reorders only exact items in parseable skills lists.
- AI bullet mode uses a single-resume deterministic title + full-description score, rewrites only
  bounded experience bullets supported by the source resume, preserves every protected section
  and structural feature, and enforces the selected review policy before upload.
- `review_before_apply` is the default and requires approval of the exact generated hash before
  upload. `skip_review` bypasses only that human-inspection prompt; all deterministic generation,
  evidence, structure, layout, relevance, upload, form, and confirmation checks remain active.
- A valid AI review-policy selection is required before any AI bullet automation starts and is
  repeated in the run confirmation. Verify Upload warns that Dice may retain a draft.
- The relevance threshold is applied before any OpenAI call or Apply click.
- Close winners, explicit clearance/citizenship/sponsorship/W2/onsite restrictions, missing
  required technologies, and visible screening questions require manual review or a skip.
- Tailored output must retain source page count after LibreOffice rendering.
- AI bullet output must retain source page count and pass bullet-only/non-target structure checks.
- A local rule always wins over model output.
- Unknown, ambiguous, external, malformed, or unconfirmed states are skipped or failed.

## Success criteria

- Zero applications below the configured threshold in the deterministic eval set.
- Zero accepted model plans that add, remove, duplicate, or rename a candidate skill.
- Zero AI bullet uploads whose behavior differs from the explicitly selected review policy.
- Zero review-required uploads without approval bound to the exact output/source/job hashes.
- Zero accepted AI bullet plans that introduce unsupported technologies or numeric claims.
- Zero submissions without a verified intended filename.
- Zero Next/Submit clicks when visible screening controls are present.
- Zero reported successes without a Dice confirmation signal.
- Source resumes remain byte-for-byte untouched.
- Preview performs zero Apply clicks; upload verification performs zero Next/Submit clicks.

## Explicit non-goals

- Generating experience, employers, dates, metrics, certifications, or qualifications.
- Unbounded or evidence-free resume rewriting; Skip review does not relax generation validation.
- Editing PDFs, scanned resumes, text boxes, or arbitrary complex Word layouts.
- Supporting external employer/ATS apply links.
- Bypassing Dice access controls, terms, bot detection, or account restrictions.
- Packaging, hosting, multi-user accounts, databases, or deployment infrastructure.
