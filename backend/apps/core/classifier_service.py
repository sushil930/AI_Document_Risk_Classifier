"""Load a persisted classifier candidate and produce a review recommendation."""

import json
import logging
from functools import lru_cache
from pathlib import Path

import joblib
from django.conf import settings
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

logger = logging.getLogger(__name__)


class ClassifierUnavailable(Exception):
    """Raised when the configured classifier cannot safely be loaded."""


@lru_cache(maxsize=4)
def _load_classifier(artifact_path: str, allow_candidate: bool):
    model_path = Path(artifact_path).expanduser().resolve()
    metadata_path = model_path.with_name("metadata.json")
    if not model_path.is_file() or not metadata_path.is_file():
        raise ClassifierUnavailable("Classifier artifact is missing its model or metadata.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        promotion_status = metadata.get("promotion_status")
        if promotion_status != "approved" and not allow_candidate:
            raise ClassifierUnavailable("Only an explicitly enabled candidate classifier is configured.")
        if metadata.get("showcase_nonproduction") and not allow_candidate:
            raise ClassifierUnavailable("Showcase candidates require explicit candidate opt-in.")
        model = joblib.load(model_path)
    except ClassifierUnavailable:
        raise
    except Exception as exc:
        logger.warning("Classifier artifact load failed (%s)", type(exc).__name__)
        raise ClassifierUnavailable("The configured classifier artifact could not be loaded.") from exc
    if not hasattr(model, "predict_proba") or set(getattr(model, "classes_", ())) != {"Low", "Medium", "High"}:
        raise ClassifierUnavailable("Classifier artifact does not expose the expected three-class probability interface.")
    return model, metadata


def clear_classifier_cache():
    """Clear cached artifacts after a settings or model-path change."""
    _load_classifier.cache_clear()


def _configured_model_path():
    configured = str(getattr(settings, "CLASSIFIER_MODEL_PATH", "") or "").strip()
    if not configured:
        return ""
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = settings.BASE_DIR.parent / path
    return str(path.resolve())


def _base_pipeline(model):
    """Return the fitted text pipeline under an optional calibration wrapper."""
    if hasattr(model, "named_steps"):
        return model
    try:
        calibrated = model.calibrated_classifiers_[0]
        frozen = calibrated.estimator
        return frozen.estimator
    except (AttributeError, IndexError, TypeError):
        return None


def _feature_signals(model, text, label):
    """Expose influential word n-grams, explicitly as model signals, not evidence."""
    pipeline = _base_pipeline(model)
    if pipeline is None:
        return {"supporting": [], "opposing": []}
    try:
        features = pipeline.named_steps["features"]
        matrix = features.transform([text])
        word_vectorizer = features.transformer_list[0][1]
        names = word_vectorizer.get_feature_names_out()
        class_index = list(pipeline.named_steps["classifier"].classes_).index(label)
        weights = pipeline.named_steps["classifier"].coef_[class_index, :len(names)]
        values = matrix[:, :len(names)].toarray()[0]
        contributions = [
            (str(names[i]), float(values[i] * weights[i]))
            for i in range(len(names))
            if values[i] > 0 and not set(str(names[i]).split()).issubset(ENGLISH_STOP_WORDS)
        ]
        supporting = sorted((item for item in contributions if item[1] > 0), key=lambda item: item[1], reverse=True)[:5]
        opposing = sorted((item for item in contributions if item[1] < 0), key=lambda item: item[1])[:5]
        return {
            "supporting": [{"term": term, "contribution": round(value, 6)} for term, value in supporting],
            "opposing": [{"term": term, "contribution": round(abs(value), 6)} for term, value in opposing],
        }
    except (AttributeError, IndexError, KeyError, ValueError, TypeError):
        logger.info("Classifier feature explanation unavailable")
        return {"supporting": [], "opposing": []}


def _nearest_examples(model_path, model, text, limit=3):
    """Return sanitized training IDs/classes based on TF-IDF cosine similarity."""
    index_path = Path(model_path).with_name("reference_index.joblib")
    if not index_path.is_file():
        return []
    try:
        index = joblib.load(index_path)
        pipeline = _base_pipeline(model)
        if pipeline is None:
            return []
        query = pipeline.named_steps["features"].transform([text])
        scores = (query @ index["vectors"].T).toarray()[0]
        ranked = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)[:limit]
        return [
            {"sample_id": str(index["examples"][i]["sample_id"]), "label": str(index["examples"][i]["label"]),
             "source_type": str(index["examples"][i].get("source_type", "")), "similarity": round(float(scores[i]), 4)}
            for i in ranked if scores[i] > 0
        ]
    except Exception as exc:
        logger.info("Classifier reference explanation unavailable (%s)", type(exc).__name__)
        return []


def classify_document(text: str):
    """Classify extracted text and return a triage result, never a harm probability."""
    normalized = (text or "").strip()
    minimum_words = max(1, int(getattr(settings, "CLASSIFIER_MIN_WORDS", 20)))
    if len(normalized.split()) < minimum_words:
        return {
            "status": "unable_to_assess",
            "predicted_label": None,
            "class_scores": {},
            "classifier_version": None,
            "review_required": True,
            "review_reasons": ["Extracted text is empty or too short for this classifier."],
            "feature_signals": {"supporting": [], "opposing": []},
            "nearest_examples": [],
        }

    model_path = _configured_model_path()
    if not model_path:
        return {
            "status": "unavailable",
            "predicted_label": None,
            "class_scores": {},
            "classifier_version": None,
            "review_required": True,
            "review_reasons": ["No classifier artifact is configured."],
            "feature_signals": {"supporting": [], "opposing": []},
            "nearest_examples": [],
        }

    allow_candidate = bool(getattr(settings, "CLASSIFIER_ALLOW_CANDIDATE", False))
    try:
        model, metadata = _load_classifier(model_path, allow_candidate)
    except ClassifierUnavailable as exc:
        return {
            "status": "unavailable",
            "predicted_label": None,
            "class_scores": {},
            "classifier_version": None,
            "review_required": True,
            "review_reasons": [str(exc)],
            "feature_signals": {"supporting": [], "opposing": []},
            "nearest_examples": [],
        }

    try:
        probabilities = model.predict_proba([normalized])[0]
        ranked = sorted(
            ((str(label), float(score)) for label, score in zip(model.classes_, probabilities)),
            key=lambda item: item[1],
            reverse=True,
        )
        predicted_label, top_score = ranked[0]
        margin = ranked[0][1] - ranked[1][1]
    except Exception as exc:
        logger.warning("Classifier inference failed (%s)", type(exc).__name__)
        return {
            "status": "unavailable",
            "predicted_label": None,
            "class_scores": {},
            "classifier_version": metadata.get("model_version"),
            "review_required": True,
            "review_reasons": ["Classifier inference failed; route this document for manual review."],
            "feature_signals": {"supporting": [], "opposing": []},
            "nearest_examples": [],
        }

    class_scores = {label: round(score, 6) for label, score in ranked}
    review_reasons = []
    thresholds = metadata.get("review_thresholds") or {}
    minimum_score = thresholds.get("minimum_class_score")
    minimum_margin = thresholds.get("minimum_top_two_margin")
    if predicted_label == "High":
        review_reasons.append("High-priority prediction always requires human review.")
    if minimum_score is not None and float(top_score) < float(minimum_score):
        review_reasons.append("Top class score is below the calibration-derived review threshold.")
    if minimum_margin is not None and margin < float(minimum_margin):
        review_reasons.append("Top two class scores are too close under the calibration-derived review threshold.")
    if metadata.get("showcase_nonproduction") or metadata.get("promotion_status") != "approved":
        review_reasons.append("This is a non-production candidate; human review is required for every prediction.")

    return {
        "status": "complete",
        "predicted_label": predicted_label,
        "class_scores": class_scores,
        "classifier_version": metadata.get("model_version"),
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "feature_signals": _feature_signals(model, normalized, predicted_label),
        "nearest_examples": _nearest_examples(model_path, model, normalized),
    }
