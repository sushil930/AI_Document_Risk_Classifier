# DocuGuard AI Classifier Upgrade Plan

**Status:** Phases 1-6 are complete for showcase use based on the project owner's approval of the AI-assisted corpus annotations. The classifier is integrated behind explicit candidate configuration, and every candidate prediction requires human review. The artifact is not production-approved.

## Target outcome

Upgrade DocuGuard from LLM-generated risk reviews to a hybrid system that also predicts document-level risk from a labeled corpus, explains the prediction, sends uncertain cases to a manual-review queue, and reports held-out class-wise performance. Keep Gemini/Groq for evidence-based findings and recommendations. A classifier score must be calibrated and described as model confidence, not as probability of harm or legal risk.

## Design decisions

- Predict one primary document risk class: **Low**, **Medium**, or **High**.
- Capture issue domains separately as optional multi-label tags: contractual, financial, privacy, security, operational, and policy. This avoids confusing the primary risk class with the kind of issue found.
- Start with a reproducible **TF-IDF word and character n-gram + Logistic Regression** baseline. It is simple to train, inspect, and deploy in the existing Django/Python backend. Consider embeddings only if evaluation shows this baseline misses important semantic cases.
- Keep the LLM responsible for quoted evidence, explanations, and recommended actions. The trained classifier provides the primary class and calibrated class scores. Store both outputs and identify their model/provider versions.
- Do not use uploaded workspace documents as training data automatically. Build the corpus from licensed/public or synthetic documents and explicitly reviewed labels. The current workspace is shared and has no login, so user uploads are not suitable as implicit training examples.
- Never display classifier confidence as a calibrated score until calibration has been measured on held-out data. Never display LLM self-reported confidence as a probability.

## Phases

### 1. Define labels and assemble a reviewed corpus

**Current phase status**

- Draft rubric created at `docs/classifier/labeling_rubric.md`.
- Corpus sourcing and annotation workflow documented at `data/classifier_corpus/README.md`.
- Manifest schema created at `data/classifier_corpus/manifest_template.csv`.
- Nine synthetic rubric examples created at `data/classifier_corpus/draft_seed_examples.csv` (three proposed examples per class). All remain `needs_dual_review` and `unassigned`; none are approved training data.
- Showcase corpus assembled at `data/docuguard_corpus_v0.1/` with 320 TXT documents, source metadata, SHA-256 hashes, and split assignments. AI annotations are in `data/ai_review_pass.csv`.
- `data/docuguard_corpus_v0.1/manifest_showcase_approved.csv` records the project owner's aggregate approval for this showcase. It preserves the AI review flags and leaves independent reviewer/adjudicator fields blank. It is **not** evidence of per-document dual-human review and is not production-approved data.
- Phase 1 is **complete for showcase use** under this explicitly limited approval. Domain review, independent dual review, source-license verification, and a final sealed evaluation set remain open for any production or performance claims. Phase 2 must not silently treat this showcase approval as dual review.

**Work**

- Write a labeling guide with Low/Medium/High definitions, examples, boundary cases, and instructions for `unable_to_assess`.
- Define whether the class describes the document's highest supported review priority or its general document-level risk. Keep issue-domain tags separate.
- Collect licensed/public or synthetic business documents with provenance. Create a versioned manifest with document ID, source, split, labels, reviewer, and rubric version. Keep raw documents outside the production uploads database.
- Have at least two reviewers label a representative subset; adjudicate disagreements and track inter-reviewer agreement.
- Detect duplicates and near-duplicates before splitting. Split by source/template (and, when applicable, organization or time) so similar versions cannot leak across train and test.

**Exit criteria**

- Every example has a traceable source, rubric version, and reviewed class.
- Each class has enough independent examples for training, calibration, and a meaningful holdout; set the numeric minimum before collecting based on domain coverage.
- The test set is sealed and is not used to select features, thresholds, or model settings.

### 2. Add a reproducible classifier baseline

**Current phase status**

- Added `backend/apps/core/classifier_training.py` and `train_classifier` management command.
- Added `docs/classifier/training.md` with manifest setup and commands.
- The command validates dual-review/adjudication by default. An explicit `--allow-showcase-owner-approval` path accepts the owner-approved AI-assisted showcase manifest and records that status in candidate metadata without creating reviewer identities.
- Trained candidate `tfidf-logreg-20261014T073323Z-faaed5b4` from 210 train rows; held-out test accuracy was 95.6% (43/45) versus 33.3% for the majority baseline. Per-class results and limitations are recorded in `docs/classifier/showcase_candidate_report.md`.
- Added tests for the showcase opt-in, approval provenance, and candidate artifact metadata. Backend core suite: 21 tests passed.
- Phase 2 is complete for showcase use. Calibration, runtime inference integration, release gates, and promotion remain future phases.

**Work**

- Add a `backend/apps/classifier/` service or equivalent module for corpus loading, validation, training, prediction, and model-version metadata.
- Train TF-IDF word and character n-gram features with Logistic Regression. Compare with a simple majority-class baseline. Apply class weights or resampling only when training data justifies it; never resample the test set.
- Save a versioned artifact and manifest (rubric/data version, feature settings, code version, training date, and class order). Load the approved artifact in Django; do not train during user uploads or web requests.
- Add a management command to validate the corpus and train/evaluate a candidate model. Require an explicit promotion step before serving a new artifact.

**Exit criteria**

- Training is reproducible from a clean environment and versioned corpus.
- Invalid labels, missing classes, leakage, and corrupt input fail with actionable messages.
- The baseline is compared against majority-class results and documented before release.

### 3. Integrate predictions and a manual-review decision

**Current phase status**

- Added `DocumentClassification` persistence and migration `0004_documentclassification.py`. Classifier status, class scores, model version, review-required flag, and reasons are linked to each analysis and exposed in its API response.
- Added the local `classifier_service.py` loader. It only loads a candidate when `CLASSIFIER_MODEL_PATH` is set and `CLASSIFIER_ALLOW_CANDIDATE=true`; missing or invalid artifacts return an unavailable/manual-review result without blocking LLM review.
- Added a calibrated candidate artifact `tfidf-logreg-20261014T075458Z-faaed5b4`. Sigmoid calibration and review thresholds use the reserved calibration split; High predictions always route to review, and all predictions from a showcase candidate require review.
- Analysis results show class scores, classifier version, and review reasons. Empty/short text gets `unable_to_assess`; High predictions, threshold flags, candidate-only status, and classifier/LLM disagreement are sent to manual review.
- Verification: backend core suite 26 passed; frontend tests 3 passed; frontend production build passed; ESLint passed; Django migration check passed; configured artifact smoke inference returned a versioned score and review flag.
- Phase 3 is complete for showcase use. Scores and review thresholds are not validated for production; calibration and release gates remain for Phase 5.

**Work**

- Run the classifier after text extraction and before or alongside the Gemini/Groq findings analysis.
- Store predicted class, per-class calibrated scores (if calibration passes), classifier version, review flag, and review reasons in a dedicated classification record linked to the document/analysis.
- Calibrate scores using a held-out calibration split (for example, sigmoid calibration; use isotonic only with sufficient data). Set the minimum confidence and top-two class-margin thresholds from validation results and the desired per-class recall/coverage trade-off—not from an arbitrary default.
- Require manual review when confidence is below the selected threshold, the top two classes are too close, text is out of distribution, extraction is insufficient, the classifier and LLM materially disagree, or the document is predicted High. Keep `unable_to_assess` distinct from Low.
- Add a review status and reason, initially `needs_review`, `reviewed`, and `dismissed`. Since this app currently has no accounts, the initial queue remains workspace-wide; do not imply reviewer identity or per-user assignment.
- Keep AI provider failures separate from classifier predictions. Never fabricate a class when either input is insufficient or the classifier artifact is unavailable.

**Exit criteria**

- Every prediction is traceable to a classifier version and extracted document.
- Low-confidence, out-of-distribution, disagreement, and unreadable cases reach manual review or `unable_to_assess` as defined.
- No score is labeled a probability of harm, compliance, or legal outcome.

### 4. Add explainability

**Current phase status**

- Added Logistic Regression word n-gram feature signals showing terms that support or oppose the predicted class; the UI labels them as model signals, not evidence.
- Candidate training now saves an explanation index made only from the train split. It stores TF-IDF vectors and sanitized sample ID, class, and source type metadata; it contains no raw example text. Inference returns the three nearest training examples by cosine similarity.
- LLM findings now carry an exact extracted-text match flag and the nearest available PDF page, DOCX paragraph/table, or generic text reference. Unmatched excerpts are disclosed in the report limitations and marked for manual verification. The result page and PDF export show these references separately from classifier explanations.
- Refreshed the configured showcase candidate with the reference index: `tfidf-logreg-20261014T084650Z-faaed5b4`.
- Verification: backend core suite 28 passed; frontend tests 3 passed; frontend lint passed; production build passed (existing large-bundle warning); migrations applied and no model changes pending; configured artifact smoke inference returned feature signals and sanitized nearest examples.
- Phase 4 is complete for showcase use. The explanation terms and similarity scores are not proof, and the source corpus remains showcase-only.

**Work**

- For Logistic Regression, show the strongest class-supporting and opposing terms for that prediction, with a clear note that these are model signals rather than proof.
- Add nearest-example explanations using TF-IDF cosine similarity against a reviewed, sanitized reference set. Show class and similarity context, not sensitive source documents or raw private text.
- Keep the existing LLM evidence excerpt, explanation, and recommended action visibly separate from classifier feature explanations.
- Ensure highlighted evidence excerpts can be traced to extracted text and page/paragraph markers.

**Exit criteria**

- Users can inspect why the classifier leaned toward a class and the source text behind LLM findings.
- Similar-document results come only from an approved reference corpus and cannot expose workspace uploads.

### 5. Evaluate, calibrate, and gate releases

**Current phase status**

- Training now writes a sealed holdout report with confusion matrix, per-class precision/recall/F1/support, Wilson 95% intervals, macro-F1, balanced accuracy, calibration metrics, and a reliability SVG.
- Reports review rate, auto-clear coverage, and test errors outside the manual-review queue using thresholds chosen only from the calibration split.
- Added a versioned release gate: independent dual-human-reviewed data, at least 30 test samples/class, macro-F1 >= 0.80, High recall >= 0.90, ECE <= 0.10, multiclass Brier <= 0.20, test auto-clear error rate <= 2%, and macro-F1 improvement >= 0.05 over majority baseline. Gate success only makes a candidate eligible for human review; it never promotes automatically.
- Evaluated showcase artifact `tfidf-logreg-20261014T085432Z-faaed5b4`: macro-F1 0.956 and balanced accuracy 0.956 on 45 test samples; ECE 0.103; test review rate 33.3%; 2 of 30 auto-cleared cases were incorrect. The gate blocks it due to AI-assisted owner-approved labels, only 15 test examples/class, ECE, and auto-clear errors.
- Verification: backend core suite 29 passed; evaluation JSON and SVG generated; release-gate checks report expected blocked status; configured artifact path refreshed. This remains showcase evaluation, not a production performance claim.
- Phase 5 is complete for showcase use. Phase 6 has not started.

**Work**

- Report confusion matrix, per-class precision, recall, F1, support, macro-F1, and balanced accuracy on the sealed holdout. Include confidence intervals where sample sizes allow.
- Evaluate calibration with reliability plots and a score such as Brier score or expected calibration error. Evaluate manual-review coverage and the errors left outside the queue.
- Select thresholds using calibration/validation data, prioritizing acceptable recall for High-risk cases and a review workload the team can handle. Freeze the threshold with the model version.
- Add regression tests for extraction, inference, class order, calibration/threshold behavior, `unable_to_assess`, disagreement routing, and artifact loading. Test with fixtures; do not call live Gemini/Groq services in classifier tests.
- Block model promotion when class-wise metrics or calibration do not meet agreed release gates. Record reviewer-approved outcomes as evaluation data only after de-identification and explicit inclusion.

**Exit criteria**

- A reproducible evaluation report exists for every promoted model and threshold.
- Per-class weaknesses and manual-review rate are visible; a single aggregate accuracy number is not used as the release decision.

### 6. Extend the dashboard and workflow

**Current phase status**

- Added a paginated manual-review queue with status, predicted priority, top-score band, reason text, date, and sort filters. Review decisions store status, a separate human-assessed class, and an optional note; the original model prediction remains unchanged.
- Added migration backfill for existing flagged classifications. Since the shared workspace has no accounts, reviewer identity is not verified or presented as attributable sign-off.
- Dashboard now reports current per-document predicted-class counts, open manual-review backlog, reviewed/dismissed totals, and recent reviewer decisions from database records.
- Added a model-performance page backed by the configured sealed evaluation report, including class metrics and intervals, confusion matrix, calibration plot/scores, review coverage/errors, rubric/model version, evaluation date, and release-gate checks.
- Analysis API and JSON/PDF exports include classifier prediction/version, review reasons/status, separate human final class and note, and LLM evidence traceability. Document history also shows the classifier result and review state.
- Verification: backend core suite 35 passed; frontend tests 6 passed; lint and production build passed (existing large-bundle warning); migrations applied; model-performance and queue API smoke checks passed.
- Phase 6 is complete for showcase use. The public shared workspace does not verify reviewers; keep that limitation visible.

**Work**

- Add a flagged/manual-review queue with filters for predicted class, score band, review reason, date, and status.
- Show current document counts by predicted class, manual-review backlog, reviewed/dismissed counts, and recent decisions from database records.
- Add a separate model-performance page for the latest sealed evaluation: per-class metrics, confusion matrix, calibration, model/rubric version, and evaluation date. Do not calculate “model accuracy” from unreviewed live predictions.
- Let reviewers mark a case reviewed and record the final class plus an optional reason; keep the prediction immutable and store reviewer corrections separately.
- Update history, JSON/PDF exports, API serializers, and frontend types to include prediction, version, review status/reason, and explainability fields.

**Exit criteria**

- Dashboard metrics derive from persisted classifications and review records.
- Review corrections do not silently overwrite model predictions or contaminate the sealed evaluation set.

## Suggested implementation order

1. Label rubric, data sourcing, privacy policy, and corpus manifest.
2. TF-IDF/Logistic Regression training command and sealed evaluation report.
3. Versioned artifact loading, prediction record, calibrated score, and review-routing backend.
4. Feature and nearest-example explanations using only approved data.
5. Manual-review queue, dashboard, and exports.
6. Threshold and class-wise evaluation gates; promote only after review.

## Main risks and controls

- **Label noise or disagreement:** rubric, dual review, adjudication, and agreement tracking.
- **Template leakage:** split by document source/template and deduplicate before splitting.
- **False precision:** calibrate on held-out data and label scores accurately; hide them if calibration is weak.
- **Sensitive data exposure:** no automatic training from uploads; sanitize nearest-example corpus; keep shared workspace limitations explicit.
- **Model drift:** version data, rubric, artifact, and threshold; periodically evaluate newly reviewed outcomes without changing the sealed test set.
- **LLM/classifier disagreement:** send to review rather than choosing one output silently.

## Definition of done

- A reviewed and versioned corpus exists with leakage-safe train/calibration/test splits.
- A trained classifier predicts Low/Medium/High and the optional issue-domain tags.
- Calibrated thresholds route uncertain, out-of-distribution, unreadable, and conflicting cases to a real review queue.
- Users can see classifier explanations and separate LLM evidence.
- A held-out, class-wise evaluation report and release gate exist.
- Dashboard and exports expose live classifications and review status without claiming live accuracy from unlabeled records.
- Automated tests cover the new classifier, thresholds, routing, explanations, and dashboard.
