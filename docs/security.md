# Security, privacy, and reliability baseline

This is a focused engineering baseline, not a complete security audit.

## Access and authorization

Dice's current terms prohibit unapproved automated navigation/retrieval. Live runs require the
explicit `DICE_AUTOMATION_AUTHORIZED=true` attestation and a per-run GUI confirmation. This flag
is not evidence of permission; the user remains responsible for retaining Dice's written
authorization and complying with applicable terms and law.

The browser adapter supports only same-origin Dice Easy Apply. External employer/ATS links are
skipped. Do not add stealth, CAPTCHA bypass, sandbox disabling, or bot-evasion behavior.

Preview is the default and never clicks Apply. Upload verification is capped at one job and never
clicks Next or Submit. Submit mode refuses unknown visible form controls instead of answering or
accepting screening questions and consents on the user's behalf.

## Secrets and local data

- `.env` contains Dice credentials and optionally an OpenAI key; it is ignored and must remain
  local with restrictive file permissions.
- `config/settings.local.json` contains personal paths and is ignored.
- Source resumes and generated `.data/` files contain PII and must not enter Git, fixtures, logs,
  screenshots, issue reports, or model eval datasets.
- Application logs may contain job titles/URLs and result reasons, never credentials, resume
  bodies, full job descriptions, prompts, API responses, or hidden model reasoning.
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

Provider timeouts, refusals, malformed results, unsafe plans, or missing skill slots skip the job.
There is no silent tailored-to-static fallback.

## Document and submission integrity

Source resumes are read-only. Tailored files are new DOCX copies under ignored `.data/`.
Paragraph count/styles, section geometry, table geometry, headers/footers, embedded media,
drawings, and legacy objects must remain stable after save/reload. Tracked changes, content
controls, text boxes, and altChunk content are rejected. Static PDFs are never edited.

Every generated DOCX is rendered through LibreOffice and must retain the source page count. A
page-count change deletes the file and skips the job. Cache manifests bind source and output
hashes to a layout-verified artifact; cached text must remain an exact character multiset of the
source.

Before Submit, the browser must verify the chosen/generated filename from the scoped file input's
`files[0].name` or exact input value. Global page text is not upload evidence. A click is never
considered success; Dice must display a visible, scoped confirmation element.

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
