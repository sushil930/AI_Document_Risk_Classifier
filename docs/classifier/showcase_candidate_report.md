# Phase 2 Showcase Candidate Report

**Candidate:** `tfidf-logreg-20261014T073323Z-faaed5b4`  
**Training data:** `data/docuguard_corpus_v0.1/manifest_showcase_approved.csv`  
**Approval mode:** owner-approved AI-assisted labels for showcase use  
**Promotion status:** candidate only; not production-approved

## Method

The candidate uses word TF-IDF unigrams/bigrams and character-boundary TF-IDF 3–5-grams with Logistic Regression. It was trained on the fixed `train` split and evaluated once on the held-out `test` split. The `calibration` split was reserved and not used in this baseline. The 20 `unable_to_assess` documents were excluded from three-class fitting.

## Dataset split

| Split | Low | Medium | High | Total |
|---|---:|---:|---:|---:|
| Train | 69 | 71 | 70 | 210 |
| Calibration (reserved) | 15 | 15 | 15 | 45 |
| Test | 15 | 15 | 15 | 45 |

## Held-out test metrics

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| Low | 0.882 | 1.000 | 0.938 | 15 |
| Medium | 1.000 | 0.867 | 0.929 | 15 |
| High | 1.000 | 1.000 | 1.000 | 15 |
| **Macro average** | **0.961** | **0.956** | **0.955** | **45** |

- Candidate accuracy: **95.6%** (43/45)
- Majority-class baseline accuracy: **33.3%** (15/45)
- Confusion matrix, rows actual and columns predicted in Low, Medium, High order: `[[15, 0, 0], [2, 13, 0], [0, 0, 15]]`

## Interpretation and limitations

These scores show that the training and evaluation pipeline runs and that this candidate fits the supplied labels. They do **not** establish real-world classification performance. The corpus labels came from an AI review pass accepted by the project owner in aggregate, the corpus is predominantly synthetic, and it has no real-source High examples. The test support is only 15 documents per class. Treat the reported scores as a showcase demonstration, not a validated estimate of generalization.

The artifact metadata records the manifest fingerprint, split counts, per-class metrics, majority baseline, owner-approved showcase mode, and non-production limitations. No calibration, threshold selection, production inference integration, or model promotion was performed in Phase 2.
