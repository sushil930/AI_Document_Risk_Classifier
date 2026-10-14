# Training the Classifier Candidate

The baseline command trains and evaluates a candidate only. The optional calibrated mode fits the artifact used by Phase 3's local inference service; neither mode promotes a production artifact.

## Corpus input

1. Copy `data/classifier_corpus/manifest_template.csv` to `data/classifier_corpus/manifest.csv` after Phase 1 reviewers approve corpus sources and labels.
2. Put already-extracted UTF-8 `.txt` files in `data/classifier_corpus/documents/`. This raw corpus directory is ignored by Git. Do not copy production workspace uploads into it.
3. Fill the manifest with provenance, SHA-256, reviewer/adjudication fields, rubric version, duplicate group, and a reviewed `train`, `calibration`, or `test` split.
4. For normal review, mark a row `approved` only after two distinct reviewers independently label it. If reviewers disagree, add a distinct adjudicator and the final adjudicated label. Leave drafts and pending rows in the manifest; the trainer skips them.
5. Keep all rows from the same near-duplicate/template group in one split. The trainer checks exact SHA-256 duplicates and duplicate-group leakage.

### Showcase-only owner-approved AI annotations

The checked-in showcase corpus has an explicit alternate path. Its manifest records aggregate owner approval of an AI annotation pass, not independent dual-human review. This opt-in is for demonstrations and model-pipeline experimentation only; artifacts remain candidate-only and must not be presented as production validated.

Run it explicitly from the repository root in PowerShell:

```powershell
\.venv\Scripts\python.exe backend\manage.py train_classifier `
  --manifest data\docuguard_corpus_v0.1\manifest_showcase_approved.csv `
  --output-dir backend\model_artifacts\candidates `
  --code-version showcase-phase-2 `
  --allow-showcase-owner-approval
```

Without `--allow-showcase-owner-approval`, the command refuses to consume this approval status. The generated metadata records `corpus_approval_mode: owner_approved_showcase_ai_assisted`, `showcase_nonproduction: true`, and the associated limitation.

For the Phase 3 inference artifact, also calibrate on the reserved split and derive review thresholds from its observed scores:

```powershell
.\.venv\Scripts\python.exe backend\manage.py train_classifier `
  --manifest data\docuguard_corpus_v0.1\manifest_showcase_approved.csv `
  --output-dir backend\model_artifacts\candidates `
  --code-version showcase-phase-3 `
  --allow-showcase-owner-approval `
  --calibrate-for-review
```

Set `CLASSIFIER_MODEL_PATH` to the generated artifact's `model.joblib` in `backend/.env` and set `CLASSIFIER_ALLOW_CANDIDATE=true` to enable it locally. `CLASSIFIER_MIN_WORDS` controls the minimum extracted text size; shorter documents return `unable_to_assess`.

`unable_to_assess` is excluded from the three-class fit. The manifest must have all three classes in train and test. Calibrated mode reserves the calibration split for sigmoid probability calibration and review-threshold selection. The sealed test split is only used after that selection to measure class-wise performance, calibration, and errors outside the review queue.

## Command

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe backend\manage.py train_classifier
```

From `backend/` in PowerShell:

```powershell
..\.venv\Scripts\python.exe manage.py train_classifier
```

The defaults read `data/classifier_corpus/manifest.csv` and write a versioned candidate under `backend/model_artifacts/candidates/`. Override paths or record a source revision with:

```powershell
..\.venv\Scripts\python.exe backend\manage.py train_classifier `
  --manifest data\classifier_corpus\manifest.csv `
  --output-dir backend\model_artifacts\candidates `
  --code-version <commit-or-release-id>
```

Each candidate contains `model.joblib`, `metadata.json`, `evaluation_report.json`, `promotion_gate.json`, `reliability.svg`, and a sanitized `reference_index.joblib`. The reference index stores TF-IDF vectors and sample ID/class/source-type metadata from the training split only; it does not store raw example text and never indexes calibration or test rows. The metadata records the reference count and `contains_raw_text: false` alongside the corpus fingerprint, rubric version, split class counts, per-class metrics, confusion matrix, baseline metrics, and `promotion_status: candidate_only`.

At inference, the UI can show Logistic Regression's strongest supporting/opposing word n-grams and the nearest training examples by TF-IDF cosine similarity. These are model signals and similarity context, not evidence or proof. LLM evidence is matched against the extracted source text and tagged with the nearest available PDF page or DOCX paragraph/table marker. Unmatched excerpts are labeled for manual verification.

## Phase 5 evaluation and release gate

Every training run writes a sealed test evaluation with the fixed class order, confusion matrix, per-class precision/recall/F1/support, Wilson 95% intervals for precision and recall, macro-F1, balanced accuracy, top-label ECE, multiclass Brier score, and a reliability SVG. The report also measures review rate, auto-clear coverage, and mistakes left outside the review queue using thresholds selected only on the calibration split.

The current conservative gate defaults in `backend/apps/core/classifier_training.py` require dual-human-reviewed data, at least 30 test examples per class, macro-F1 >= 0.80, High recall >= 0.90, ECE <= 0.10, multiclass Brier <= 0.20, no more than 2% errors among test examples auto-cleared from review, and a macro-F1 improvement of at least 0.05 over the majority baseline. Thresholds are versioned with the artifact. A passing gate only marks a candidate eligible for review; automatic promotion is disabled.

The showcase corpus is expected to fail this gate: it is owner-approved AI-assisted, has only 15 test examples per class, and its held-out test results show calibration and auto-clear errors above the configured limits. The report is useful for demonstrating the evaluation pipeline, not for making performance claims or promoting this model. Increase the corpus and secure independent labels before considering release.
