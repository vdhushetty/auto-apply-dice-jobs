# Product scope

## Goal and users

The product helps an individual job seeker apply selectively to matching Dice roles using either
three truthful cloud-focused resumes or one user-provided base resume. The primary user owns the
Dice account, every source resume, and every factual claim in them.

## Primary workflows

1. Configure Dice credentials, authorization attestation, search terms, and a bounded run limit.
2. Select AWS/Azure/GCP variants, or select one base DOCX for AI resume optimization.
3. Choose static selection, tailored skill prioritization, or AI resume optimization. For AI
   optimization, explicitly choose **Review before apply** or **Skip review** before starting.
4. Start in preview mode. Build a bounded round-robin sample across the configured searches,
   read each sampled full job description, rank resume-eligible jobs by match score, and inspect
   the highest-fit jobs without clicking Apply.
5. Optionally open only the single highest-ranked eligible candidate, permit at most one resume
   file-selection attempt, and stop whether its filename check succeeds or fails without
   advancing the wizard. Dice may retain that one draft.
6. Use submit mode only when ready. It processes Data Engineer, Data Analyst, Machine Learning,
   AI ML, Gen AI, and Agentic AI in that fixed order. Within each role it finishes each search
   result's JD → optimization → upload → confirmation flow before opening the next result.
7. Follow the Live Automation panel through preflight, resume preparation, Easy Apply, filename
   verification, and the final outcome; every rejected candidate or stopped run exposes a bounded
   reason without resume contents, credentials, API keys, or local paths.

## Functional policy

- Static and tailored modes require exactly three user-approved variants. AI optimization requires
  exactly one user-approved DOCX.
- Full-description ranking uses a deterministic candidate pool of four times the run limit, with
  at least one candidate slot per nonempty search bucket, before the application cap is applied.
- Static mode uploads the highest-scoring original file unchanged.
- Tailored mode selects a DOCX and reorders only exact items in parseable skills lists.
- AI mode records a single-resume title + full-description score but does not use it as an initial
  rejection gate. It can optimize up to twelve supported summary, skills, experience, and project
  paragraphs in place while preserving exact paragraph count/order and all protected structure.
- If an AI optimization plan introduces a technology absent from its cited source items, the app makes
  one more conservative, source-bound request; a second invalid plan is skipped.
- In the one-job **Verify Upload** mode only, an AI no-op or explicit no-relevant-change result
  may use the same user-approved base DOCX to test Dice's filename selection. The Live Automation
  panel labels this **verify-only fallback**, and the run still never clicks Next or Submit.
  Submit mode never uses this fallback: it requires a validated, job-specific AI output.
- `review_before_apply` is the default and requires approval of the exact generated hash before
  upload. `skip_review` bypasses only that human-inspection prompt; all deterministic generation,
  evidence, structure, layout, relevance, upload, form, and confirmation checks remain active.
- A valid AI review-policy selection is required before any AI optimization starts and is
  repeated in the run confirmation. Verify Upload warns that it may leave one Dice draft after
  its one permitted file-selection attempt.
- The relevance threshold is applied before any OpenAI call or Apply click in static and tailored
  modes. AI resume optimization instead attempts a full-description curation and relies on source
  evidence, document, upload, and submission checks.
- Close winners, explicit clearance/citizenship/sponsorship/W2/onsite restrictions, missing
  required technologies, and visible screening questions require manual review or a skip.
- Tailored output must retain source page count after LibreOffice rendering.
- AI-optimized output must retain source page count and pass in-place-text-only structure checks.
- A local rule always wins over model output.
- Unknown, ambiguous, external, malformed, or unconfirmed states are skipped or failed.
- A successful credential test remains visibly verified for the current app process. Its
  Dice-domain cookies may be reused in memory after protected-page validation; expired reuse
  falls back to the normal credential login.

## Success criteria

- Zero applications below the configured threshold in the deterministic eval set.
- Zero accepted model plans that add, remove, duplicate, or rename a candidate skill.
- Zero AI-optimized uploads whose behavior differs from the explicitly selected review policy.
- Zero review-required uploads without approval bound to the exact output/source/job hashes.
- Zero accepted AI optimization plans that introduce unsupported technologies or numeric claims.
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
