import io
import json
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pymupdf as fitz
from docx import Document as WordDocument
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .models import Analysis, ClassificationReview, Document, DocumentClassification
from .services import analyze_text, attach_evidence_references, complete, validate_report, ProviderError
from .classifier_training import _calibration_metrics, _metrics, _read_approved_rows, _review_routing, train_candidate

REPORT = {"document_type":"Service agreement","overall_priority":"Medium","summary":"One item merits review.","findings":[{"issue":"Open ended term","severity":"Medium","evidence":"The term renews automatically.","explanation":"Renewal may occur without active approval.","recommended_action":"Add a renewal notice period."}],"limitations":["Review the full document."]}

class AnalyzerTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def upload_txt(self, name="agreement.txt", content=b"This agreement has enough meaningful text for a substantive document risk review. "+b"Terms apply. "*8):
        return self.client.post("/api/documents/", {"file":SimpleUploadedFile(name, content, content_type="text/plain")}, format="multipart")

    def test_api_has_no_auth_routes_and_workspace_is_public(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 404)
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 200)

    @override_settings(GEMINI_API_KEY="gemini-secret-test", GROQ_API_KEY="groq-secret-test")
    def test_settings_exposes_provider_status_but_not_api_keys(self):
        response = self.client.get("/api/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["providers"]["gemini_configured"])
        self.assertTrue(response.data["providers"]["groq_configured"])
        self.assertNotIn("gemini-secret-test", str(response.data))
        self.assertNotIn("groq-secret-test", str(response.data))

    def test_extracts_pdf_docx_txt(self):
        from .extraction import extract_text
        pdf = fitz.open(); page = pdf.new_page(); page.insert_text((72,72), "Readable PDF content"); buf=pdf.tobytes()
        txt, kind = extract_text(SimpleUploadedFile("a.pdf",buf))
        self.assertIn("Readable PDF content", txt); self.assertEqual(kind,"pdf")
        doc = WordDocument(); doc.add_paragraph("Readable Word content"); out=io.BytesIO(); doc.save(out)
        txt, kind = extract_text(SimpleUploadedFile("a.docx",out.getvalue()))
        self.assertIn("Readable Word content",txt); self.assertEqual(kind,"docx")
        txt, kind = extract_text(SimpleUploadedFile("a.txt",b"Readable plain text"))
        self.assertEqual(txt,"Readable plain text"); self.assertEqual(kind,"txt")

    def test_upload_rejects_unsupported_and_keeps_empty_pdf_for_ocr_state(self):
        bad = self.client.post("/api/documents/", {"file":SimpleUploadedFile("x.exe",b"not executable")}, format="multipart")
        self.assertEqual(bad.status_code,400)
        pdf=fitz.open();pdf.new_page();empty=pdf.tobytes()
        response=self.client.post("/api/documents/", {"file":SimpleUploadedFile("scan.pdf",empty,content_type="application/pdf")}, format="multipart")
        self.assertEqual(response.status_code,201)
        result=self.client.post(f"/api/documents/{response.data['id']}/analyze/",{"include_ai":True},format="json")
        self.assertEqual(result.data["status"],"unable_to_assess")
        self.assertIn("OCR",result.data["error_message"])

    def test_preview_extracts_text_without_persisting_the_upload(self):
        response=self.client.post("/api/documents/preview/", {"file":SimpleUploadedFile("draft.txt",b"Preview text stays temporary.",content_type="text/plain")}, format="multipart")
        self.assertEqual(response.status_code,200); self.assertEqual(response.data["text"],"Preview text stays temporary.")
        self.assertEqual(Document.objects.count(),0)

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.services.complete")
    def test_analyze_saves_report_and_exports(self, complete):
        complete.return_value=json.dumps(REPORT)
        upload=self.upload_txt(); self.assertEqual(upload.status_code,201)
        response=self.client.post(f"/api/documents/{upload.data['id']}/analyze/",{"model":"gemini-3.8-flash","include_ai":True},format="json")
        self.assertEqual(response.status_code,201); self.assertEqual(response.data["overall_priority"],"Medium")
        self.assertEqual(self.client.get(f"/api/analyses/{response.data['id']}/export/json/").status_code,200)
        pdf=self.client.get(f"/api/analyses/{response.data['id']}/export/pdf/")
        self.assertEqual(pdf.status_code,200); self.assertEqual(pdf["Content-Type"],"application/pdf")

    def test_workspace_documents_are_shared_without_login(self):
        upload=self.upload_txt()
        client=APIClient()
        self.assertEqual(client.get(f"/api/documents/{upload.data['id']}/").status_code,200)
        self.assertEqual(client.delete(f"/api/documents/{upload.data['id']}/").status_code,204)

    def test_dashboard_uses_real_records_and_history_filters(self):
        upload=self.upload_txt(); document=Document.objects.get(pk=upload.data["id"])
        Analysis.objects.create(document=document,selected_model="gemini-3.8-flash",status="complete",overall_priority="High",summary="Summary",findings=[],limitations=[])
        dashboard=self.client.get("/api/dashboard/")
        self.assertEqual(dashboard.data["total_documents"],1); self.assertEqual(dashboard.data["high_priority"],1)
        self.assertEqual(self.client.get("/api/analyses/?priority=High").data["count"],1)

    def test_invalid_llm_report_is_rejected(self):
        with self.assertRaises(ValueError): validate_report({"overall_priority":"unknown"})

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_TIMEOUT_SECONDS=120)
    @patch("apps.core.services.genai.Client")
    def test_gemini_request_uses_server_key_and_json_mode(self, client_factory):
        client_factory.return_value.models.generate_content.return_value.text = json.dumps(REPORT)
        self.assertEqual(complete("gemini-3.8-flash", "system prompt", "document text"), json.dumps(REPORT))
        self.assertEqual(client_factory.call_args.kwargs["api_key"], "test-key")
        request = client_factory.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], "gemini-3.8-flash")
        self.assertEqual(request["config"].response_mime_type, "application/json")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.services.genai.Client")
    def test_gemini_server_error_exposes_http_status_without_provider_details(self, client_factory):
        class UpstreamFailure(Exception):
            code = 503

        client_factory.return_value.models.generate_content.side_effect = UpstreamFailure("private provider detail")
        with self.assertRaises(ProviderError) as error:
            complete("gemini-3.8-flash", "system prompt", "document text")
        self.assertIn("HTTP 503", str(error.exception))
        self.assertNotIn("private provider detail", str(error.exception))
        client_factory.return_value.close.assert_called_once()

    @override_settings(GROQ_API_KEY="test-groq-key", GROQ_BASE_URL="https://api.groq.com/openai/v1", GROQ_TIMEOUT_SECONDS=45)
    @patch("apps.core.services.OpenAI")
    def test_groq_request_uses_server_key_and_json_mode(self, client_factory):
        client_factory.return_value.chat.completions.create.return_value.choices[0].message.content = json.dumps(REPORT)
        self.assertEqual(complete("groq:openai/gpt-oss-120b", "system prompt", "document text"), json.dumps(REPORT))
        self.assertEqual(client_factory.call_args.kwargs["api_key"], "test-groq-key")
        self.assertEqual(client_factory.call_args.kwargs["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(client_factory.call_args.kwargs["timeout"], 45)
        request = client_factory.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "openai/gpt-oss-120b")
        self.assertEqual(request["response_format"], {"type":"json_object"})
        client_factory.return_value.close.assert_called_once()

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.services.complete")
    def test_malformed_provider_json_gets_one_controlled_repair(self, complete):
        complete.side_effect=["not json",json.dumps(REPORT)]
        report, unable, _used_model=analyze_text("A meaningful document with enough actual content to assess. "*3,"gemini-3.8-flash")
        self.assertIsNone(unable); self.assertEqual(report["overall_priority"],"Medium"); self.assertEqual(complete.call_count,2)

    @override_settings(GEMINI_API_KEY="test-key", MAX_DOCUMENT_CHARS=50000)
    @patch("apps.core.services.complete")
    def test_long_document_is_chunked_and_consolidated(self, complete):
        complete.return_value=json.dumps(REPORT)
        report, unable, _used_model=analyze_text("Section text. "*1000,"gemini-3.8-flash")
        self.assertIsNone(unable); self.assertTrue(report["findings"]); self.assertGreaterEqual(complete.call_count,3)

    @override_settings(
        GEMINI_API_KEY="test-gemini-key",
        GROQ_API_KEY="test-groq-key",
        GEMINI_MODELS=["gemini-3.8-flash"],
        GROQ_MODELS=["openai/gpt-oss-120b"],
        GROQ_FALLBACK_MODEL="openai/gpt-oss-120b",
        ANALYSIS_MODELS=["gemini-3.8-flash", "groq:openai/gpt-oss-120b"],
    )
    @patch("apps.core.services.complete")
    def test_gemini_unavailability_retries_full_analysis_with_groq(self, complete):
        complete.side_effect = [ProviderError("Gemini returned a temporary server error (HTTP 503).", fallback_allowed=True), json.dumps(REPORT)]
        report, unable, used_model = analyze_text("A meaningful document with enough actual content to assess. "*3, "gemini-3.8-flash")
        self.assertIsNone(unable)
        self.assertEqual(report["overall_priority"], "Medium")
        self.assertEqual(used_model, "groq:openai/gpt-oss-120b")
        self.assertEqual(complete.call_count, 2)
        self.assertEqual(complete.call_args_list[0].args[0], "gemini-3.8-flash")
        self.assertEqual(complete.call_args_list[1].args[0], "groq:openai/gpt-oss-120b")

    @override_settings(
        GEMINI_API_KEY="test-gemini-key",
        GROQ_API_KEY="test-groq-key",
        GEMINI_MODELS=["gemini-3.8-flash"],
        GROQ_MODELS=["openai/gpt-oss-120b"],
        GROQ_FALLBACK_MODEL="openai/gpt-oss-120b",
        ANALYSIS_MODELS=["gemini-3.8-flash", "groq:openai/gpt-oss-120b"],
    )
    @patch("apps.core.services.complete", side_effect=ProviderError("Gemini is rate limiting requests. Wait briefly and try again."))
    def test_rate_limits_do_not_silently_switch_to_groq(self, complete):
        with self.assertRaises(ProviderError) as error:
            analyze_text("A meaningful document with enough actual content to assess. "*3, "gemini-3.8-flash")
        self.assertIn("rate limiting", str(error.exception))
        self.assertEqual(complete.call_count, 1)

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.services.complete", side_effect=ProviderError("Could not connect to the Gemini API. Check your internet connection and retry."))
    def test_provider_connection_failure_has_safe_message(self, _complete):
        with self.assertRaises(ProviderError) as error:
            analyze_text("A meaningful document with enough actual content to assess. "*3,"gemini-3.8-flash")
        self.assertIn("Could not connect to the Gemini API",str(error.exception)); self.assertNotIn("https://",str(error.exception))

    @override_settings(GEMINI_API_KEY="", GROQ_API_KEY="")
    def test_missing_provider_key_returns_actionable_error_without_fake_analysis(self):
        upload=self.upload_txt()
        result=self.client.post(f"/api/documents/{upload.data['id']}/analyze/",{"model":"gemini-3.8-flash","include_ai":True},format="json")
        self.assertEqual(result.status_code,502); self.assertIn("GEMINI_API_KEY",result.data["detail"])
        self.assertEqual(Analysis.objects.count(),1); self.assertEqual(Analysis.objects.first().status,"failed")


class ClassifierTrainingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project_root = Path(__file__).resolve().parents[3]
        cls.manifest = cls.project_root / "data" / "docuguard_corpus_v0.1" / "manifest_showcase_approved.csv"

    def test_showcase_manifest_requires_explicit_nonproduction_opt_in(self):
        with self.assertRaisesRegex(ValueError, "--allow-showcase-owner-approval"):
            _read_approved_rows(self.manifest)

    def test_showcase_rows_load_with_owner_approval_provenance(self):
        rows, skipped_unreviewed, skipped_unassessable = _read_approved_rows(
            self.manifest, allow_showcase_owner_approval=True
        )
        self.assertEqual(len(rows), 300)
        self.assertEqual(skipped_unreviewed, 0)
        self.assertEqual(skipped_unassessable, 20)
        self.assertEqual(
            Counter(row["approval_mode"] for row in rows),
            {"owner_approved_showcase_ai_assisted": 300},
        )
        self.assertEqual(Counter(row["split"] for row in rows), {"train": 210, "calibration": 45, "test": 45})

    def test_training_writes_candidate_only_metadata_for_showcase_data(self):
        with tempfile.TemporaryDirectory() as output_root:
            artifact_dir, metadata = train_candidate(
                self.manifest,
                Path(output_root),
                code_version="showcase-phase-2",
                allow_showcase_owner_approval=True,
            )
            self.assertTrue((artifact_dir / "model.joblib").is_file())
            self.assertTrue((artifact_dir / "metadata.json").is_file())
            self.assertEqual(metadata["promotion_status"], "candidate_only")
            self.assertTrue(metadata["showcase_nonproduction"])
            self.assertEqual(metadata["corpus_approval_mode"], "owner_approved_showcase_ai_assisted")
            self.assertEqual(metadata["skipped_unassessable_rows"], 20)
            self.assertEqual(metadata["sample_counts"]["test"], {"High": 15, "Low": 15, "Medium": 15})
            self.assertTrue((artifact_dir / "evaluation_report.json").is_file())
            self.assertTrue((artifact_dir / "reliability.svg").is_file())
            self.assertTrue((artifact_dir / "promotion_gate.json").is_file())
            self.assertEqual(metadata["promotion_gate"]["status"], "blocked")
            self.assertIn("dual_human_reviewed_corpus", metadata["promotion_gate"]["blocking_reasons"])

    def test_calibration_derives_thresholds_from_reserved_split(self):
        with tempfile.TemporaryDirectory() as output_root:
            _artifact_dir, metadata = train_candidate(
                self.manifest,
                Path(output_root),
                code_version="showcase-phase-3",
                allow_showcase_owner_approval=True,
                calibrate_for_review=True,
            )
        self.assertTrue(metadata["class_scores_calibrated"])
        self.assertIsNotNone(metadata["review_thresholds"])
        self.assertEqual(metadata["review_thresholds"]["calibration_auto_errors"], 0)
        self.assertIn("ece", metadata["metrics"]["sealed_test_calibration"])
        self.assertIn("errors_outside_review_queue", metadata["metrics"]["sealed_test_review_routing"])

    def test_evaluation_reports_classwise_intervals_calibration_and_queue_errors(self):
        labels = ["Low", "Medium", "High", "High"]
        predictions = ["Low", "Medium", "Medium", "High"]
        probabilities = np.array([[.8,.1,.1],[.1,.8,.1],[.1,.7,.2],[.1,.1,.8]])
        metrics = _metrics(labels, predictions)
        calibration = _calibration_metrics(labels, probabilities, ["Low", "Medium", "High"])
        routing = _review_routing(labels, probabilities, ["Low", "Medium", "High"], {"minimum_class_score":.75,"minimum_top_two_margin":.2})
        self.assertIn("recall_95_ci", metrics["per_class"]["High"])
        self.assertIn("balanced_accuracy", metrics)
        self.assertGreaterEqual(calibration["ece"], 0)
        self.assertEqual(routing["errors_outside_review_queue"], 0)
        self.assertEqual(routing["review_count"], 2)

    def test_training_artifact_contains_sanitized_train_only_explanation_index(self):
        import joblib
        with tempfile.TemporaryDirectory() as output_root:
            artifact_dir, metadata = train_candidate(
                self.manifest, Path(output_root), code_version="phase-4",
                allow_showcase_owner_approval=True, calibrate_for_review=True,
            )
            index = joblib.load(artifact_dir / "reference_index.joblib")
        self.assertEqual(metadata["explanation_index"], {"enabled": True, "training_examples": 210, "contains_raw_text": False})
        self.assertEqual(len(index["examples"]), 210)
        self.assertEqual(set(index["examples"][0]), {"sample_id", "label", "source_type"})
        self.assertNotIn("text", index["examples"][0])
        self.assertEqual(index["vectors"].shape[0], 210)


class EvidenceReferenceTests(TestCase):
    def test_evidence_is_matched_and_tied_to_extracted_page_or_flagged(self):
        report = {"findings": [
            {"evidence": "Supplier may retain all records.", "issue": "Retention"},
            {"evidence": "Invented sentence.", "issue": "Unverified"},
        ], "limitations": []}
        result = attach_evidence_references(report, "[Page 4]\nSupplier may retain all records.")
        self.assertTrue(result["findings"][0]["evidence_verified"])
        self.assertEqual(result["findings"][0]["source_references"], ["Page 4"])
        self.assertFalse(result["findings"][1]["evidence_verified"])
        self.assertTrue(any("could not be matched exactly" in item for item in result["limitations"]))


class ClassifierServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def upload_txt(self, name="agreement.txt", content=b"This agreement has enough meaningful text for a substantive document risk review. " + b"Terms apply. " * 8):
        return self.client.post("/api/documents/", {"file": SimpleUploadedFile(name, content, content_type="text/plain")}, format="multipart")

    def setUp(self):
        self.client = APIClient()

    def upload_txt(self, name="agreement.txt", content=b"This agreement has enough meaningful text for a substantive document risk review. " + b"Terms apply. " * 8):
        return self.client.post("/api/documents/", {"file": SimpleUploadedFile(name, content, content_type="text/plain")}, format="multipart")

    @override_settings(CLASSIFIER_MODEL_PATH="", CLASSIFIER_MIN_WORDS=20)
    def test_short_text_is_unable_to_assess(self):
        from .classifier_service import classify_document
        result = classify_document("Only three words.")
        self.assertEqual(result["status"], "unable_to_assess")
        self.assertIsNone(result["predicted_label"])
        self.assertTrue(result["review_required"])

    @override_settings(
        CLASSIFIER_MODEL_PATH="fake/model.joblib",
        CLASSIFIER_ALLOW_CANDIDATE=True,
        CLASSIFIER_MIN_WORDS=5,
    )
    @patch("apps.core.classifier_service._load_classifier")
    def test_high_candidate_prediction_is_always_routed_to_review(self, load_classifier):
        from .classifier_service import classify_document

        class FakeClassifier:
            classes_ = ["High", "Low", "Medium"]

            def predict_proba(self, _texts):
                return [[0.82, 0.10, 0.08]]

        load_classifier.return_value = (
            FakeClassifier(),
            {
                "model_version": "showcase-candidate-test",
                "promotion_status": "candidate_only",
                "showcase_nonproduction": True,
                "review_thresholds": {"minimum_class_score": 0.6, "minimum_top_two_margin": 0.2},
            },
        )
        result = classify_document("This is a long enough document for this classifier test to run successfully.")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["predicted_label"], "High")
        self.assertTrue(result["review_required"])
        self.assertTrue(any("High-priority" in reason for reason in result["review_reasons"]))
        self.assertTrue(any("non-production candidate" in reason for reason in result["review_reasons"]))

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.views.classify_document")
    @patch("apps.core.services.complete")
    def test_analysis_persists_and_returns_classifier_decision(self, complete, classify):
        classify.return_value = {
            "status": "complete",
            "predicted_label": "Medium",
            "class_scores": {"Medium": 0.71, "Low": 0.19, "High": 0.10},
            "classifier_version": "showcase-candidate-test",
            "review_required": True,
            "review_reasons": ["Close class scores require human review."],
        }
        complete.return_value = json.dumps(REPORT)
        upload = self.upload_txt()
        response = self.client.post(
            f"/api/documents/{upload.data['id']}/analyze/",
            {"model": "gemini-3.8-flash", "include_ai": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        classification = response.data["classification"]
        self.assertEqual(classification["predicted_label"], "Medium")
        self.assertTrue(classification["review_required"])
        self.assertEqual(DocumentClassification.objects.count(), 1)
        self.assertEqual(DocumentClassification.objects.get().analysis_id, response.data["id"])
        self.assertEqual(ClassificationReview.objects.get().status, "needs_review")
        exported = self.client.get(f"/api/analyses/{response.data['id']}/export/json/")
        exported_data = json.loads(exported.content)
        self.assertEqual(exported_data["classification"]["review_decision"]["status"], "needs_review")
        self.assertTrue(any("Close class scores" in reason for reason in exported_data["classification"]["review_reasons"]))

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("apps.core.views.classify_document")
    @patch("apps.core.services.complete")
    def test_classifier_and_llm_disagreement_routes_to_manual_review(self, complete, classify):
        classify.return_value = {
            "status": "complete",
            "predicted_label": "High",
            "class_scores": {"High": 0.8, "Medium": 0.15, "Low": 0.05},
            "classifier_version": "showcase-candidate-test",
            "review_required": True,
            "review_reasons": ["High-priority prediction always requires human review."],
        }
        low_report = {**REPORT, "overall_priority": "Low"}
        complete.return_value = json.dumps(low_report)
        upload = self.upload_txt()
        response = self.client.post(
            f"/api/documents/{upload.data['id']}/analyze/",
            {"model": "gemini-3.8-flash", "include_ai": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["classification"]["review_required"])
        self.assertTrue(any("priorities differ" in reason for reason in response.data["classification"]["review_reasons"]))


class ReviewWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        upload = self.client.post("/api/documents/", {
            "file": SimpleUploadedFile("review-case.txt", b"Review workflow document text is sufficiently long for document analysis." * 3, content_type="text/plain")
        }, format="multipart")
        self.document = Document.objects.get(pk=upload.data["id"])
        self.analysis = Analysis.objects.create(document=self.document, selected_model="gemini-3.8-flash", status="complete", overall_priority="Medium", summary="Review the data retention terms.")
        self.classification = DocumentClassification.objects.create(
            document=self.document, analysis=self.analysis, status="complete", predicted_label="High",
            class_scores={"High": .8, "Medium": .15, "Low": .05}, classifier_version="phase6-test",
            review_required=True, review_reasons=["High-priority prediction always requires human review."],
        )
        self.review = ClassificationReview.objects.create(classification=self.classification)

    def test_queue_filters_by_status_priority_reason_and_date(self):
        response = self.client.get("/api/reviews/?status=needs_review&priority=High&score_band=high&reason=human&start=2020-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        item = response.data["results"][0]
        self.assertEqual(item["document_name"], "review-case.txt")
        self.assertEqual(item["review_status"], "needs_review")
        self.assertAlmostEqual(item["top_class_score"], .8)
        self.assertEqual(item["analysis_id"], self.analysis.pk)

    def test_human_decision_is_stored_separately_from_prediction(self):
        response = self.client.post(f"/api/reviews/{self.classification.pk}/decision/", {
            "status": "reviewed", "final_label": "Medium", "note": "The broad clause is limited by section 8."
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.classification.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.classification.predicted_label, "High")
        self.assertEqual(self.review.final_label, "Medium")
        self.assertEqual(self.review.status, "reviewed")
        self.assertIn("limited by section 8", self.review.note)

    def test_reviewed_state_requires_final_human_label(self):
        response = self.client.post(f"/api/reviews/{self.classification.pk}/decision/", {"status": "reviewed"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "needs_review")

    def test_dashboard_reports_live_backlog_and_review_decisions(self):
        dashboard = self.client.get("/api/dashboard/")
        self.assertEqual(dashboard.data["manual_review_backlog"], 1)
        self.assertEqual(dashboard.data["predicted_distribution"], [{"predicted_label": "High", "count": 1}])
        self.review.status = "reviewed"; self.review.final_label = "Medium"; self.review.save()
        dashboard = self.client.get("/api/dashboard/")
        self.assertEqual(dashboard.data["manual_review_backlog"], 0)
        self.assertEqual(dashboard.data["reviewed_count"], 1)
        self.assertEqual(dashboard.data["recent_review_decisions"][0]["final_label"], "Medium")

    def test_dashboard_distribution_uses_only_latest_classification_per_document(self):
        newer_analysis = Analysis.objects.create(document=self.document, selected_model="gemini-3.8-flash", status="complete", overall_priority="Low", summary="Later review.")
        DocumentClassification.objects.create(
            document=self.document, analysis=newer_analysis, status="complete", predicted_label="Low",
            class_scores={"Low": .7, "Medium": .2, "High": .1}, classifier_version="phase6-later",
            review_required=False, review_reasons=[],
        )
        dashboard = self.client.get("/api/dashboard/")
        self.assertEqual(dashboard.data["predicted_distribution"], [{"predicted_label": "Low", "count": 1}])

    @override_settings(CLASSIFIER_MODEL_PATH="")
    def test_model_performance_endpoint_handles_missing_artifact_report(self):
        response = self.client.get("/api/model-performance/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["available"])
