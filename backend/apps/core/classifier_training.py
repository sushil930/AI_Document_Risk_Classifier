"""Offline, corpus-backed training for the initial document risk classifier.

This module deliberately does not run from document upload or analysis views.
Dual-reviewed rows are the default. Owner-approved AI-assisted showcase labels
require an explicit opt-in and are recorded as non-production in metadata.
"""

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline


RISK_LABELS = ("Low", "Medium", "High")
RELEASE_GATES = {
    "minimum_test_support_per_class": 30,
    "minimum_macro_f1": 0.80,
    "minimum_high_recall": 0.90,
    "maximum_ece": 0.10,
    "maximum_multiclass_brier": 0.20,
    "maximum_test_auto_clear_error_rate": 0.02,
    "minimum_macro_f1_gain_over_baseline": 0.05,
}
REQUIRED_FIELDS = {
    "sample_id", "document_path", "source_type", "source_reference",
    "license_or_generation_note", "document_sha256", "assessment_status",
    "final_primary_risk", "reviewer_1_id", "reviewer_1_label",
    "reviewer_2_id", "reviewer_2_label", "adjudicator_id",
    "adjudicated_label", "rubric_version", "review_status",
    "duplicate_group", "split",
}


def _read_approved_rows(manifest_path: Path, allow_showcase_owner_approval: bool = False):
    manifest_path = manifest_path.resolve()
    corpus_root = manifest_path.parent.resolve()
    if not manifest_path.is_file():
        raise ValueError(f"Corpus manifest not found: {manifest_path}")

    records = []
    seen_ids = set()
    duplicate_splits = defaultdict(set)
    fingerprints = {}
    skipped_unreviewed = 0
    skipped_unassessable = 0
    skipped_showcase = 0

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Manifest is missing required columns: " + ", ".join(sorted(missing)))

        for line_number, row in enumerate(reader, start=2):
            sample_id = (row.get("sample_id") or "").strip()
            if not sample_id:
                raise ValueError(f"Manifest row {line_number}: sample_id is required.")
            if sample_id in seen_ids:
                raise ValueError(f"Manifest row {line_number}: duplicate sample_id {sample_id}.")
            seen_ids.add(sample_id)

            review_status = (row.get("review_status") or "").strip()
            showcase_approval = review_status == "owner_approved_showcase"
            if showcase_approval and not allow_showcase_owner_approval:
                skipped_unreviewed += 1
                skipped_showcase += 1
                continue
            if review_status != "approved" and not showcase_approval:
                skipped_unreviewed += 1
                continue

            if showcase_approval:
                showcase_required = (
                    "annotation_method", "owner_approval_basis", "owner_approved_by",
                    "owner_approved_at", "ai_review_human_check",
                )
                missing_showcase = [field for field in showcase_required if not (row.get(field) or "").strip()]
                if missing_showcase:
                    raise ValueError(
                        f"Manifest row {line_number}: owner-approved showcase row is missing "
                        + ", ".join(missing_showcase)
                    )
                if not (row.get("annotation_method") or "").startswith("AI-assisted annotation"):
                    raise ValueError(f"Manifest row {line_number}: showcase annotation_method must identify AI-assisted labels.")
                if (row.get("ai_review_human_check") or "").strip().lower() not in {"yes", "no"}:
                    raise ValueError(f"Manifest row {line_number}: ai_review_human_check must be yes or no.")

            assessment_status = (row.get("assessment_status") or "").strip()
            if assessment_status == "unable_to_assess":
                if (row.get("final_primary_risk") or "").strip():
                    raise ValueError(f"Manifest row {line_number}: unable_to_assess rows must not have a risk label.")
                if showcase_approval and (row.get("ai_review_primary_label") or "").strip():
                    raise ValueError(f"Manifest row {line_number}: unable_to_assess showcase rows must not have an AI risk label.")
                skipped_unassessable += 1
                continue
            if assessment_status != "assessable":
                raise ValueError(f"Manifest row {line_number}: assessment_status must be assessable or unable_to_assess.")

            label = (row.get("final_primary_risk") or "").strip()
            if label not in RISK_LABELS:
                raise ValueError(f"Manifest row {line_number}: final_primary_risk must be Low, Medium, or High.")
            if showcase_approval:
                ai_label = (row.get("ai_review_primary_label") or "").strip()
                if ai_label not in RISK_LABELS or ai_label != label:
                    raise ValueError(f"Manifest row {line_number}: final label must match the owner-approved AI review label.")
                approval_mode = "owner_approved_showcase_ai_assisted"
            else:
                reviewer_1 = (row.get("reviewer_1_id") or "").strip()
                reviewer_2 = (row.get("reviewer_2_id") or "").strip()
                if not reviewer_1 or not reviewer_2 or reviewer_1 == reviewer_2:
                    raise ValueError(f"Manifest row {line_number}: approved labels require two distinct reviewer IDs.")
                label_1 = (row.get("reviewer_1_label") or "").strip()
                label_2 = (row.get("reviewer_2_label") or "").strip()
                adjudicator = (row.get("adjudicator_id") or "").strip()
                adjudicated = (row.get("adjudicated_label") or "").strip()
                if label_1 not in RISK_LABELS or label_2 not in RISK_LABELS:
                    raise ValueError(f"Manifest row {line_number}: both reviewers must have valid primary labels.")
                if label_1 != label_2:
                    if not adjudicator or adjudicator in {reviewer_1, reviewer_2} or adjudicated not in RISK_LABELS:
                        raise ValueError(f"Manifest row {line_number}: reviewer disagreement requires a distinct adjudicator and valid adjudicated_label.")
                    expected_label = adjudicated
                else:
                    if adjudicated and adjudicated != label_1:
                        raise ValueError(f"Manifest row {line_number}: adjudicated_label conflicts with reviewer agreement.")
                    expected_label = label_1
                if label != expected_label:
                    raise ValueError(f"Manifest row {line_number}: final_primary_risk does not match the reviewed/adjudicated label.")
                approval_mode = "dual_human_review"

            for field in ("source_type", "source_reference", "license_or_generation_note", "rubric_version", "duplicate_group"):
                if not (row.get(field) or "").strip():
                    raise ValueError(f"Manifest row {line_number}: {field} is required for approved rows.")
            split = (row.get("split") or "").strip().lower()
            if split not in {"train", "calibration", "test"}:
                raise ValueError(f"Manifest row {line_number}: split must be train, calibration, or test.")
            duplicate_group = row["duplicate_group"].strip()
            duplicate_splits[duplicate_group].add(split)

            relative_path = Path((row.get("document_path") or "").strip())
            if not str(relative_path) or relative_path.is_absolute():
                raise ValueError(f"Manifest row {line_number}: document_path must be relative to the corpus directory.")
            document_path = (corpus_root / relative_path).resolve()
            if corpus_root not in document_path.parents:
                raise ValueError(f"Manifest row {line_number}: document_path escapes the corpus directory.")
            if not document_path.is_file():
                raise ValueError(f"Manifest row {line_number}: source document does not exist: {relative_path}.")
            raw = document_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            expected_digest = (row.get("document_sha256") or "").strip().lower()
            if not expected_digest or digest != expected_digest:
                raise ValueError(f"Manifest row {line_number}: document_sha256 is missing or does not match the source file.")
            if digest in fingerprints:
                other_id, other_split = fingerprints[digest]
                raise ValueError(f"Manifest row {line_number}: exact duplicate of {other_id} appears in {other_split} and {split}; deduplicate before training.")
            fingerprints[digest] = (sample_id, split)

            try:
                text = raw.decode("utf-8-sig").strip()
            except UnicodeDecodeError as exc:
                raise ValueError(f"Manifest row {line_number}: corpus source must be UTF-8 text extracted before training.") from exc
            if not text:
                raise ValueError(f"Manifest row {line_number}: source text is empty.")

            records.append({"sample_id": sample_id, "text": text, "label": label, "split": split, "source_type": row["source_type"].strip(), "rubric_version": row["rubric_version"].strip(), "sha256": digest, "approval_mode": approval_mode})

    for group, splits in duplicate_splits.items():
        if len(splits) > 1:
            raise ValueError(f"Duplicate group {group} crosses dataset splits: {', '.join(sorted(splits))}.")
    if not records:
        if skipped_showcase and not allow_showcase_owner_approval:
            raise ValueError("This manifest contains owner-approved showcase annotations. Re-run with --allow-showcase-owner-approval to train a non-production candidate.")
        raise ValueError("No approved, assessable corpus rows were found. Complete dual review and adjudication before training.")
    rubric_versions = {record["rubric_version"] for record in records}
    if len(rubric_versions) != 1:
        raise ValueError("Approved training rows use multiple rubric versions; curate a single rubric version for this candidate.")
    return records, skipped_unreviewed, skipped_unassessable


def _wilson_interval(successes, trials, z=1.959963984540054):
    if not trials:
        return None
    proportion = successes / trials
    denominator = 1 + z * z / trials
    center = (proportion + z * z / (2 * trials)) / denominator
    radius = z * np.sqrt((proportion * (1 - proportion) + z * z / (4 * trials)) / trials) / denominator
    return [round(float(max(0, center - radius)), 6), round(float(min(1, center + radius)), 6)]


def _numpy_json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _metrics(labels, predictions):
    report = classification_report(labels, predictions, labels=list(RISK_LABELS), output_dict=True, zero_division=0)
    matrix = confusion_matrix(labels, predictions, labels=list(RISK_LABELS))
    for index, label in enumerate(RISK_LABELS):
        tp = int(matrix[index, index])
        predicted = int(matrix[:, index].sum())
        support = int(matrix[index, :].sum())
        report[label]["precision_95_ci"] = _wilson_interval(tp, predicted)
        report[label]["recall_95_ci"] = _wilson_interval(tp, support)
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_f1": float(f1_score(labels, predictions, labels=list(RISK_LABELS), average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "per_class": report,
        "confusion_matrix": matrix.tolist(),
    }


def _calibration_metrics(labels, probabilities, classes, bin_count=10):
    classes = list(classes)
    encoded = np.zeros_like(probabilities, dtype=float)
    class_lookup = {label: index for index, label in enumerate(classes)}
    for row, label in enumerate(labels):
        encoded[row, class_lookup[label]] = 1.0
    brier = float(np.mean(np.sum((probabilities - encoded) ** 2, axis=1)))
    predicted_indices = probabilities.argmax(axis=1)
    confidences = probabilities.max(axis=1)
    correct = np.array([classes[index] == label for index, label in zip(predicted_indices, labels)], dtype=float)
    bins = []
    ece = 0.0
    for bin_index in range(bin_count):
        lower, upper = bin_index / bin_count, (bin_index + 1) / bin_count
        mask = (confidences >= lower) & ((confidences < upper) if bin_index < bin_count - 1 else (confidences <= upper))
        count = int(mask.sum())
        if count:
            mean_confidence = float(confidences[mask].mean())
            accuracy = float(correct[mask].mean())
            ece += count / len(labels) * abs(mean_confidence - accuracy)
        else:
            mean_confidence = accuracy = None
        bins.append({"lower": lower, "upper": upper, "count": count, "mean_confidence": mean_confidence, "accuracy": accuracy})
    return {"method": "top-label expected calibration error with 10 equal-width bins", "ece": float(ece), "multiclass_brier": brier, "reliability_bins": bins}


def _review_routing(labels, probabilities, classes, thresholds):
    classes = list(classes)
    if not thresholds:
        review = [True] * len(labels)
        reason = "No calibration-derived routing thresholds configured; route all cases to review."
    else:
        ordered = np.sort(probabilities, axis=1)
        top = probabilities.max(axis=1)
        margin = ordered[:, -1] - ordered[:, -2]
        predicted = [classes[index] for index in probabilities.argmax(axis=1)]
        review = [
            bool(label == "High"
            or score < float(thresholds["minimum_class_score"])
            or gap < float(thresholds["minimum_top_two_margin"]))
            for label, score, gap in zip(predicted, top, margin)
        ]
        reason = "High predictions are always reviewed; remaining cases use calibration-derived score and margin thresholds."
    auto_indices = [index for index, is_review in enumerate(review) if not is_review]
    errors_outside_queue = sum(classes[int(probabilities[index].argmax())] != labels[index] for index in auto_indices)
    review_count = sum(review)
    return {
        "policy": reason,
        "total": len(labels),
        "review_count": review_count,
        "review_rate": review_count / len(labels) if labels else 0.0,
        "auto_clear_count": len(auto_indices),
        "auto_clear_coverage": len(auto_indices) / len(labels) if labels else 0.0,
        "errors_outside_review_queue": int(errors_outside_queue),
        "auto_clear_error_rate": errors_outside_queue / len(auto_indices) if auto_indices else 0.0,
        "auto_clear_accuracy": 1 - errors_outside_queue / len(auto_indices) if auto_indices else None,
    }


def _promotion_gate(metrics, calibration, routing, thresholds, calibrated, approval_mode):
    per_class = metrics["per_class"]
    checks = {
        "dual_human_reviewed_corpus": approval_mode == "dual_human_review",
        "calibrated_scores_available": bool(calibrated),
        "calibration_derived_thresholds_available": bool(thresholds),
        "minimum_test_support_met": all(per_class[label]["support"] >= RELEASE_GATES["minimum_test_support_per_class"] for label in RISK_LABELS),
        "macro_f1_gate_met": metrics["macro_f1"] >= RELEASE_GATES["minimum_macro_f1"],
        "high_recall_gate_met": per_class["High"]["recall"] >= RELEASE_GATES["minimum_high_recall"],
        "ece_gate_met": calibration["ece"] <= RELEASE_GATES["maximum_ece"],
        "brier_gate_met": calibration["multiclass_brier"] <= RELEASE_GATES["maximum_multiclass_brier"],
        "auto_clear_error_gate_met": routing["auto_clear_error_rate"] <= RELEASE_GATES["maximum_test_auto_clear_error_rate"],
        "beats_majority_baseline": metrics["macro_f1"] >= metrics.get("majority_baseline_macro_f1", 0) + RELEASE_GATES["minimum_macro_f1_gain_over_baseline"],
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {"status": "eligible_for_review" if not reasons else "blocked", "checks": checks, "blocking_reasons": reasons, "criteria": RELEASE_GATES.copy(), "automatic_promotion": False}


def _reliability_svg(calibration, model_version):
    width, height, left, top, plot = 640, 430, 72, 55, 330
    def point(x, y):
        return left + x * plot, top + (1 - y) * plot
    diagonal_start, diagonal_end = point(0, 0), point(1, 1)
    circles = []
    for item in calibration["reliability_bins"]:
        if item["count"] and item["mean_confidence"] is not None:
            x, y = point(item["mean_confidence"], item["accuracy"])
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#4658d8"><title>n={item["count"]}; confidence={item["mean_confidence"]:.3f}; accuracy={item["accuracy"]:.3f}</title></circle>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/><text x="{width/2}" y="26" text-anchor="middle" font-family="sans-serif" font-size="16">Test-set reliability: {model_version}</text>
<line x1="{left}" y1="{top+plot}" x2="{left+plot}" y2="{top}" stroke="#9aa3b2" stroke-dasharray="6 5"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot}" stroke="#303846"/><line x1="{left}" y1="{top+plot}" x2="{left+plot}" y2="{top+plot}" stroke="#303846"/>
<text x="{left+plot/2}" y="{top+plot+48}" text-anchor="middle" font-family="sans-serif" font-size="12">Mean predicted confidence</text>
<text x="19" y="{top+plot/2}" transform="rotate(-90 19 {top+plot/2})" text-anchor="middle" font-family="sans-serif" font-size="12">Observed accuracy</text>
{''.join(circles)}<text x="{left}" y="{top+plot+18}" font-family="sans-serif" font-size="10">0</text><text x="{left+plot}" y="{top+plot+18}" text-anchor="end" font-family="sans-serif" font-size="10">1</text>
<text x="{left}" y="{height-14}" font-family="sans-serif" font-size="11">ECE={calibration['ece']:.4f} | Multiclass Brier={calibration['multiclass_brier']:.4f} | Dashed line=ideal</text></svg>'''


def _select_review_thresholds(labels, probabilities, classes):
    """Choose maximum calibration coverage with zero errors among auto-cleared rows.

    High predictions always go to manual review. For the other labels, search
    thresholds from observed calibration scores and margins. This is a
    showcase policy derived from the supplied calibration split, not a release
    guarantee.
    """
    labels = list(labels)
    classes = list(classes)
    if not labels or not all(label in RISK_LABELS for label in labels):
        raise ValueError("Calibration data must contain labeled Low, Medium, and High examples.")
    if set(labels) != set(RISK_LABELS):
        raise ValueError("Calibration split must include Low, Medium, and High examples.")

    predictions = [classes[index] for index in probabilities.argmax(axis=1)]
    ordered = np.sort(probabilities, axis=1)
    top_scores = probabilities.max(axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    confidence_candidates = sorted({0.0, 1.000001, *(float(x) + 1e-9 for x in top_scores)})
    margin_candidates = sorted({0.0, 1.000001, *(float(x) + 1e-9 for x in margins)})

    best = None
    for minimum_score in confidence_candidates:
        for minimum_margin in margin_candidates:
            auto_indices = [
                index for index, prediction in enumerate(predictions)
                if prediction != "High"
                and top_scores[index] >= minimum_score
                and margins[index] >= minimum_margin
            ]
            errors = sum(predictions[index] != labels[index] for index in auto_indices)
            if errors:
                continue
            candidate = (len(auto_indices), -minimum_score, -minimum_margin, minimum_score, minimum_margin)
            if best is None or candidate > best:
                best = candidate

    if best is None:
        return {"minimum_class_score": 1.000001, "minimum_top_two_margin": 1.000001, "calibration_auto_coverage": 0.0, "calibration_auto_errors": 0}
    auto_coverage = best[0] / len(labels)
    return {
        "minimum_class_score": round(best[3], 8),
        "minimum_top_two_margin": round(best[4], 8),
        "calibration_auto_coverage": round(auto_coverage, 6),
        "calibration_auto_errors": 0,
    }


def train_candidate(
    manifest_path: Path,
    output_root: Path,
    code_version: str = "unrecorded",
    allow_showcase_owner_approval: bool = False,
    calibrate_for_review: bool = False,
    include_explanation_index: bool = True,
):
    """Train/evaluate a non-promoted candidate from an approved split manifest."""
    records, skipped_unreviewed, skipped_unassessable = _read_approved_rows(
        Path(manifest_path), allow_showcase_owner_approval=allow_showcase_owner_approval
    )
    by_split = {name: [row for row in records if row["split"] == name] for name in ("train", "calibration", "test")}
    if not by_split["train"] or not by_split["test"]:
        raise ValueError("Approved rows must include non-empty train and test splits; reserve calibration rows for the next phase.")
    if calibrate_for_review and not by_split["calibration"]:
        raise ValueError("Calibrated review routing requires a non-empty calibration split.")
    train_labels = {row["label"] for row in by_split["train"]}
    missing_train = set(RISK_LABELS) - train_labels
    if missing_train:
        raise ValueError("Training split is missing classes: " + ", ".join(sorted(missing_train)))
    test_labels = {row["label"] for row in by_split["test"]}
    missing_test = set(RISK_LABELS) - test_labels
    if missing_test:
        raise ValueError("Test split is missing classes: " + ", ".join(sorted(missing_test)))

    train_texts = [row["text"] for row in by_split["train"]]
    train_y = [row["label"] for row in by_split["train"]]
    test_texts = [row["text"] for row in by_split["test"]]
    test_y = [row["label"] for row in by_split["test"]]

    vectorizers = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), strip_accents="unicode", sublinear_tf=True, max_features=30000)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), strip_accents="unicode", sublinear_tf=True, max_features=30000)),
    ])
    classifier = Pipeline([
        ("features", vectorizers),
        ("classifier", LogisticRegression(max_iter=1000, random_state=17)),
    ])
    classifier.fit(train_texts, train_y)
    candidate_metrics = _metrics(test_y, classifier.predict(test_texts))

    model_for_artifact = classifier
    review_thresholds = None
    calibrated_metrics = None
    if calibrate_for_review:
        calibration_labels = [row["label"] for row in by_split["calibration"]]
        missing_calibration = set(RISK_LABELS) - set(calibration_labels)
        if missing_calibration:
            raise ValueError("Calibration split is missing classes: " + ", ".join(sorted(missing_calibration)))
        calibrator = CalibratedClassifierCV(FrozenEstimator(classifier), method="sigmoid")
        calibration_texts = [row["text"] for row in by_split["calibration"]]
        calibrator.fit(calibration_texts, calibration_labels)
        calibration_probabilities = calibrator.predict_proba(calibration_texts)
        review_thresholds = _select_review_thresholds(calibration_labels, calibration_probabilities, calibrator.classes_)
        model_for_artifact = calibrator
        calibrated_metrics = _metrics(test_y, calibrator.predict(test_texts))

    baseline = DummyClassifier(strategy="most_frequent")
    baseline.fit(train_texts, train_y)
    baseline_metrics = _metrics(test_y, baseline.predict(test_texts))

    evaluation_probabilities = model_for_artifact.predict_proba(test_texts)
    evaluation_metrics = _metrics(test_y, model_for_artifact.predict(test_texts))
    evaluation_metrics["majority_baseline_macro_f1"] = baseline_metrics["macro_f1"]
    test_calibration = _calibration_metrics(test_y, evaluation_probabilities, model_for_artifact.classes_)
    calibration_split_metrics = None
    if calibrate_for_review:
        calibration_split_metrics = _calibration_metrics(calibration_labels, calibration_probabilities, model_for_artifact.classes_)
    review_routing = _review_routing(test_y, evaluation_probabilities, model_for_artifact.classes_, review_thresholds)
    showcase_mode = any(row["approval_mode"] == "owner_approved_showcase_ai_assisted" for row in records)
    approval_mode = "owner_approved_showcase_ai_assisted" if showcase_mode else "dual_human_review"
    promotion_gate = _promotion_gate(
        evaluation_metrics, test_calibration, review_routing, review_thresholds,
        calibrate_for_review, approval_mode,
    )
    test_fingerprint = hashlib.sha256("\n".join(
        f"{row['sample_id']}:{row['sha256']}:{row['label']}" for row in sorted(by_split["test"], key=lambda x: x["sample_id"])
    ).encode("utf-8")).hexdigest()

    manifest_fingerprint = hashlib.sha256("\n".join(
        f"{row['sample_id']}:{row['sha256']}:{row['label']}:{row['split']}" for row in sorted(records, key=lambda x: x["sample_id"])
    ).encode("utf-8")).hexdigest()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_version = f"tfidf-logreg-{timestamp}-{manifest_fingerprint[:8]}"
    artifact_dir = Path(output_root) / model_version
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model.joblib"
    temporary_model = artifact_dir / "model.joblib.tmp"
    joblib.dump(model_for_artifact, temporary_model)
    os.replace(temporary_model, model_path)

    reference_count = 0
    if include_explanation_index:
        # Reference vectors use training rows only; no calibration/test examples
        # participate in explanations. Raw example text is deliberately omitted.
        training_features = classifier.named_steps["features"].transform(train_texts)
        reference_index = {
            "vectors": training_features,
            "examples": [
                {"sample_id": row["sample_id"], "label": row["label"], "source_type": row["source_type"]}
                for row in by_split["train"]
            ],
        }
        joblib.dump(reference_index, artifact_dir / "reference_index.joblib")
        reference_count = len(by_split["train"])

    limitations = ["A candidate artifact is not production-approved.", "The sealed test split is used for evaluation only and never selects thresholds."]
    if showcase_mode:
        limitations.append("Training labels include AI-generated annotations accepted in aggregate by the owner for showcase use; they are not independently dual-human reviewed.")
    metadata = {
        "model_version": model_version,
        "model_type": "TF-IDF word+character n-grams with Logistic Regression" + (" and sigmoid calibration" if calibrate_for_review else ""),
        "risk_labels": list(RISK_LABELS),
        "rubric_version": records[0]["rubric_version"],
        "manifest_sha256": manifest_fingerprint,
        "code_version": code_version,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_counts": {split: dict(Counter(row["label"] for row in rows)) for split, rows in by_split.items()},
        "skipped_unreviewed_rows": skipped_unreviewed,
        "skipped_unassessable_rows": skipped_unassessable,
        "feature_settings": {"word_ngrams": [1, 2], "char_wb_ngrams": [3, 5], "max_features_per_vectorizer": 30000},
        "metrics": {"candidate": candidate_metrics, "calibrated_candidate": calibrated_metrics, "majority_baseline": baseline_metrics, "sealed_test": evaluation_metrics, "sealed_test_calibration": test_calibration, "sealed_test_review_routing": review_routing},
        "promotion_status": "candidate_only",
        "corpus_approval_mode": "owner_approved_showcase_ai_assisted" if showcase_mode else "dual_human_review",
        "showcase_nonproduction": showcase_mode,
        "class_scores_calibrated": bool(calibrate_for_review),
        "review_thresholds": review_thresholds,
        "promotion_gate": promotion_gate,
        "explanation_index": {"enabled": bool(include_explanation_index), "training_examples": reference_count, "contains_raw_text": False},
        "limitations": limitations,
    }
    metadata_path = artifact_dir / "metadata.json"
    temporary_metadata = artifact_dir / "metadata.json.tmp"
    temporary_metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=_numpy_json_default), encoding="utf-8")
    os.replace(temporary_metadata, metadata_path)
    evaluation_report = {
        "model_version": model_version,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest_fingerprint,
        "sealed_test_split_sha256": test_fingerprint,
        "test_support": len(test_y),
        "test_class_counts": dict(Counter(test_y)),
        "class_order": list(RISK_LABELS),
        "scores_calibrated": bool(calibrate_for_review),
        "calibration_split_in_sample": calibration_split_metrics,
        "test_metrics": evaluation_metrics,
        "test_calibration": test_calibration,
        "review_thresholds_from_calibration_split": review_thresholds,
        "test_review_routing": review_routing,
        "promotion_gate": promotion_gate,
        "limitations": limitations + ["Wilson intervals are wide for small class supports; the showcase test split is not statistically adequate for production claims."],
    }
    (artifact_dir / "evaluation_report.json").write_text(json.dumps(evaluation_report, indent=2, ensure_ascii=False, default=_numpy_json_default), encoding="utf-8")
    (artifact_dir / "reliability.svg").write_text(_reliability_svg(test_calibration, model_version), encoding="utf-8")
    (artifact_dir / "promotion_gate.json").write_text(json.dumps(promotion_gate, indent=2, default=_numpy_json_default), encoding="utf-8")
    return artifact_dir, metadata
