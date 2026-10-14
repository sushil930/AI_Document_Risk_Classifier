# Classifier Corpus Staging Area

This directory is for the separately curated classifier dataset. It is **not** the production upload store and is not used by the current app or a training command.

## Current contents

- `manifest_template.csv`: provenance, annotation, privacy, duplicate, and split metadata schema.
- `draft_seed_examples.csv`: nine short synthetic cases, three per proposed primary class, for reviewing the rubric. Their labels are drafts; every row is `needs_dual_review` and has no train/calibration/test split.

These short examples are rubric probes, not a sufficient training corpus. Do not train on them or report model performance from them.

## Sourcing rules

1. Prefer synthetic, public-domain, or explicitly licensed source documents whose terms permit this use. Record a source URL or generation note and the applicable license/terms in the manifest.
2. Do not copy user uploads from the shared DocuGuard workspace into this directory or use them for training by default. The workspace has no login and uploaded business documents may be sensitive.
3. For any later opt-in contribution workflow, define consent, de-identification, retention, deletion, and access controls before collecting documents.
4. Keep source documents outside the production uploads database. Store only approved corpus materials in the training-data location, with access and retention documented.
5. Calculate a SHA-256 digest for each source document. Detect exact and near duplicates and assign a `duplicate_group` before splitting.
6. Split by source, template, or organization group so related documents cannot cross training, calibration, and test sets. Keep the test set sealed.
7. Numeric class minimums and release targets remain unset until a domain reviewer approves corpus scope and class coverage. Do not treat a small balanced seed set as evidence of adequate performance.

## Annotation workflow

Use `docs/classifier/labeling_rubric.md`. Two reviewers independently annotate each candidate, including assessment status, primary label, issue tags, evidence, and rationale; disagreements and disagreements about a High concern are adjudicated. Keep the original labels. Mark a row `approved` only after review is complete. Leave `split` unassigned until duplicate groups are known and the split design is approved.

## Manifest fields

`manifest_template.csv` defines the expected fields. Keep source references and label metadata in the manifest; keep raw source documents in a controlled corpus store, not inside the production upload area. For synthetic seed examples, the excerpt itself is included in `draft_seed_examples.csv` only so reviewers can assess the proposed labels.
