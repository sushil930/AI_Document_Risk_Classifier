# DocuGuard Showcase Corpus v0.1

This folder contains a 320-document corpus assembled for the DocuGuard showcase. It is separate from production document uploads.

## Files

- `documents/`: 320 UTF-8 text files used by the corpus manifest.
- `original_formats/`: retained DOCX and PDF examples where available.
- `manifest.csv`: original candidate metadata and proposed split assignments.
- `candidate_seed_notes.csv`: candidate labels and rationales; keep separate from blind annotation.
- `reviewer_blind_worksheet.csv`: blank per-document annotation worksheet.
- `labeling_rubric.md`: rubric version 0.1-draft.
- `manifest_showcase_approved.csv`: AI-assisted annotations accepted in aggregate by the project owner for this showcase.

## Showcase approval and limits

The project owner approved the AI review pass in aggregate on 2026-10-14. The resulting manifest records `review_status=owner_approved_showcase`, retains the AI review flags, and leaves independent reviewer and adjudicator fields blank. The annotations were not independently labeled by two human reviewers. Do not describe the corpus as dual-human reviewed or use it to support production, legal, compliance, or model-performance claims.

The AI pass contains 300 assessable documents and 20 `unable_to_assess` examples. Its class labels are proposed annotations accepted for demonstration. `unable_to_assess` is a separate assessment status, not a fourth risk class.

`DOC-0057` and `DOC-0151` are identical empty files. They are assigned the same duplicate group in the showcase-approved manifest and remain `unable_to_assess`.

Source and license information is recorded in the manifest, but the external terms have not been independently verified. Confirm attribution and license obligations before redistributing the corpus.

The Phase 2 training command defaults to dual-reviewed rows with `review_status=approved`. It accepts `manifest_showcase_approved.csv` only with the explicit `--allow-showcase-owner-approval` flag. Resulting artifacts are labeled AI-assisted and non-production in their metadata.
