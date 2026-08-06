# Security, privacy, and reliability baseline

This is a focused engineering baseline, not a complete security audit.

## Access and authorization

Dice's current terms prohibit unapproved automated navigation/retrieval. Live runs require the
explicit `DICE_AUTOMATION_AUTHORIZED=true` attestation and a per-run GUI confirmation. This flag
is not evidence of permission; the user remains responsible for retaining Dice's written
authorization and complying with applicable terms and law.

The browser adapter supports only same-origin Dice Easy Apply. External employer/ATS links are
skipped. Do not add stealth, CAPTCHA bypass, sandbox disabling, or bot-evasion behavior.

Preview is the default and never clicks Apply. Upload verification opens only the single
highest-ranked eligible job, permits at most one resume file-selection attempt, and stops whether
the filename check succeeds or fails; it never clicks Next or Submit. The confirmation warns that
Dice may retain that one draft. Submit mode refuses unknown visible form controls instead of
answering or accepting screening questions and consents on the user's behalf.

## Secrets and local data

- `.env` contains Dice credentials and optionally an OpenAI key; it is ignored and must remain
  local with restrictive file permissions. The masked API-key field is persisted only when its
  explicit checkbox is selected; the key never enters settings JSON, manifests, reports, or logs.
- A rejected AI bullet plan may receive one conservative retry, but each response is validated
  locally against the exact cited source bullets before any DOCX is created or uploaded.
- `config/settings.local.json` contains personal paths and the selected non-secret AI review
  policy; it is ignored.
- Source resumes and generated `.data/` files contain PII and must not enter Git, fixtures, logs,
  screenshots, issue reports, or model eval datasets.
- Application logs may contain job titles/URLs and result reasons, never credentials, resume
  bodies, full job descriptions, prompts, API responses, or hidden model reasoning.
- A tested Dice session is held only in process memory. Only Dice-domain cookies are eligible for
  transfer to the run browser, reuse must pass a protected-profile check, and cookie names/values
  are never persisted or logged. Credential edits invalidate the cached session immediately.
- Rotate credentials immediately if an ignored file is accidentally exposed; deleting Git
  history alone is not sufficient.

## AI trust boundary

The job description is data and can contain prompt-injection text. The OpenAI developer
instruction explicitly marks it untrusted. Requests use Structured Outputs, no tools, no
conversation state, and `store=False`.

Schema compliance is not authorization. Local validation additionally requires:

- exact job-description evidence substrings;
- known slot IDs only;
- one exact permutation of existing candidate-owned item IDs;
- no additions, omissions, duplicates, or renamed skills; and
- at least one meaningful order change.

AI bullet tailoring separately limits plans to four target experience bullets and two net-new
bullets. Every replacement must cite its target/source IDs, preserve source-supported technology
and numeric claims, avoid duplicate text, and leave protected resume sections untouched. The
default model is `gpt-5.6-sol` with low reasoning; an intentional `OPENAI_MODEL` environment
override is captured before the worker starts. Preview neither requires a key nor constructs an
OpenAI client.

Provider timeouts, refusals, malformed results, unsafe plans, or missing editable content skip the
job. There is no generated-to-static fallback in Submit mode. The sole exception is an explicit,
visible **verify-only fallback**: when AI reports no safe non-identical bullet change, the
one-job, no-submit upload check may select the exact user-approved base DOCX to prove Dice's
filename flow. It cannot advance or submit an application.

## Document and submission integrity

Source resumes are read-only. Tailored files are new DOCX copies under ignored `.data/`.
Paragraph count/styles, section geometry, table geometry, headers/footers, embedded media,
drawings, and legacy objects must remain stable after save/reload. Tracked changes, content
controls, text boxes, and altChunk content are rejected. Static PDFs are never edited.

Every generated DOCX is rendered through LibreOffice and must retain the source page count. A
page-count change deletes the file and skips the job. Skill-order cache manifests bind source and
output hashes to a layout-verified artifact. AI bullet caches additionally store the validated
plan and bind the job/model/prompt; cached copies rerun bullet-only/non-target structure
validation. When `review_before_apply` is selected, the app opens each AI-generated file and
records approval bound to exact source/output/job/manifest hashes before upload. Any later change
invalidates that approval. When `skip_review` is selected, the human-inspection callback is
omitted, but all evidence, structure, page-count, matching, filename, form, and confirmation
checks remain mandatory. Skip review is not a validation bypass.

The GUI requires one of the two review policies before starting AI bullet automation and repeats
the selected policy in the per-run confirmation. The Skip review confirmation states that it
bypasses only human inspection. Verify Upload also warns that Dice may retain drafts.

Before Submit, the browser must verify the chosen/generated filename from the scoped file input's
`files[0].name` or exact input value. Global page text is not upload evidence. A click is never
considered success; Dice must display a visible, scoped confirmation element.

Dice occasionally renders an unlabeled file input in the initial Easy Apply wizard. The browser
accepts it as the resume field only when it is the sole file input, its surrounding context does
not indicate a cover letter or other non-resume document, and its `accept` contract includes PDF,
DOC, DOCX, and RTF. The exact selected filename is still required before advancing or submitting.
The requested job-detail path, canonical structured-data URL, post-navigation path, and Easy Apply
job identifier must agree. File selection requires exactly one resume/CV-labelled input or the
narrowed Dice document-picker contract above; ambiguous or unrelated attachment fields fail
closed.

The UI progress channel is observational only: callback failures cannot change browser behavior.
Messages are length-bounded and redact secret-like tokens and local paths. It distinguishes the
read-only ranking preflight from upload activity and records exact skip/failure categories without
including job-description or resume bodies.

## Remaining risks

- Dice markup and policy can change without notice; selectors and authorization must be reviewed
  before live use.
- Local `.env` credentials are plaintext at rest. OS account/disk security is assumed.
- Selenium Manager may resolve/download a compatible driver at runtime; that path still needs a
  live, authorized cross-platform verification matrix.
- Deterministic taxonomy scoring can miss novel technology terms. Raising the threshold reduces
  false positives but may increase false negatives.
- LibreOffice pagination can differ from Microsoft Word. Equal LibreOffice page counts are a
  fail-closed baseline, not a guarantee of identical rendering in every Word version.
- Deterministic checks cannot prove that every generated phrase matches the user's intended
  meaning. `review_before_apply` mitigates that risk; selecting `skip_review` explicitly accepts
  it for bounded, locally validated bullet changes.
