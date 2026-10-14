import json
import logging
import os
import re
import textwrap
from pathlib import Path
from io import BytesIO
from django.conf import settings
from django.db.models import Case, Count, F, FloatField, OuterRef, Subquery, When
from django.db.models.functions import Cast
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Document, Analysis, DocumentClassification, ClassificationReview, WorkspaceSettings
from .serializers import DocumentSerializer, AnalysisSerializer, SettingsSerializer, ReviewQueueSerializer, ReviewActivitySerializer
from .extraction import extract_text
from .services import analyze_text, answer_question, attach_evidence_references, ProviderError
from .classifier_service import classify_document

logger = logging.getLogger(__name__)
def health(request): return JsonResponse({"status":"ok"})


def _ensure_review_record(classification):
    if classification.review_required:
        ClassificationReview.objects.get_or_create(classification=classification)

class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    def get_queryset(self):
        queryset = Document.objects.prefetch_related("analyses", "classifications")
        search = self.request.query_params.get("search", "").strip()
        return queryset.filter(original_filename__icontains=search) if search else queryset
    def perform_destroy(self, instance):
        storage, name = instance.file.storage, instance.file.name
        instance.delete()
        if name: storage.delete(name)
    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if not upload: return Response({"detail":"Choose a file to upload."}, status=400)
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024: return Response({"detail":f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit."}, status=400)
        suffix = os.path.splitext(upload.name)[1].lower()
        allowed_types = {".pdf":{"application/pdf","application/octet-stream"},".docx":{"application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/octet-stream"},".txt":{"text/plain","application/octet-stream"}}
        if suffix not in allowed_types or upload.content_type not in allowed_types[suffix]: return Response({"detail":"File extension and content type must match a PDF, DOCX, or TXT document."}, status=400)
        try: text, suffix = extract_text(upload)
        except Exception as exc:
            logger.info("Upload extraction rejected (%s)", type(exc).__name__)
            return Response({"detail":"This file could not be read. Upload a valid PDF, DOCX, or UTF-8 TXT file."}, status=400)
        name = os.path.basename(upload.name).replace("\x00", "")[:255] or f"document.{suffix}"
        item = Document.objects.create(file=upload, original_filename=name, file_type=suffix, file_size=upload.size, extracted_text=text)
        return Response(DocumentSerializer(item).data, status=201)
    @action(detail=False, methods=["post"], url_path="preview")
    def preview_upload(self, request):
        upload = request.FILES.get("file")
        if not upload: return Response({"detail":"Choose a file to preview."}, status=400)
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024: return Response({"detail":f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit."}, status=400)
        suffix = os.path.splitext(upload.name)[1].lower()
        allowed_types = {".pdf":{"application/pdf","application/octet-stream"},".docx":{"application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/octet-stream"},".txt":{"text/plain","application/octet-stream"}}
        if suffix not in allowed_types or upload.content_type not in allowed_types[suffix]: return Response({"detail":"File extension and content type must match a PDF, DOCX, or TXT document."}, status=400)
        try: text, file_type = extract_text(upload)
        except Exception as exc:
            logger.info("Preview extraction rejected (%s)", type(exc).__name__)
            return Response({"detail":"This file could not be read. Upload a valid PDF, DOCX, or UTF-8 TXT file."}, status=400)
        return Response({"text":text[:12000],"truncated":len(text)>12000,"file_type":file_type,"characters":len(text)})
    @action(detail=True, methods=["post"])
    def analyze(self, request, pk=None):
        document = self.get_object()
        preferences, _ = WorkspaceSettings.objects.get_or_create(pk=1, defaults={"default_model":settings.GEMINI_DEFAULT_MODEL})
        model = request.data.get("model") or preferences.default_model
        include_ai = request.data.get("include_ai", False)
        if not isinstance(include_ai, bool): return Response({"detail":"include_ai must be true or false."}, status=400)
        if include_ai and model not in settings.ANALYSIS_MODELS: return Response({"detail":"Select an available configured model."}, status=400)
        document.status = "analyzing"; document.save(update_fields=["status"])
        classification_payload = classify_document(document.extracted_text)
        classification_payload["classifier_version"] = classification_payload.get("classifier_version") or ""
        classification = DocumentClassification.objects.create(document=document, **classification_payload)
        if not include_ai:
            unreadable = not re.sub(r"\[Page\s+\d+\]\s*", "", document.extracted_text).strip()
            unable_reason = (
                "No readable text could be extracted. This may be a scanned PDF; OCR is required."
                if unreadable else next(iter(classification.review_reasons), "The classifier could not meaningfully assess this document.")
            )
            unable = unreadable or classification.status != "complete" or not classification.predicted_label
            priority = classification.predicted_label if not unable else None
            summary = (
                f"The local classifier predicted {priority} priority. This is a triage result; use Ask AI for an optional text-based review."
                if priority else unable_reason
            )
            limitations = [
                "No LLM review was requested. Classifier output is a triage recommendation and requires human verification.",
                "This result does not establish that the document is safe or compliant.",
            ]
            if unable:
                limitations.insert(0, unable_reason)
            result = Analysis.objects.create(
                document=document,
                selected_model="local-classifier",
                status="unable_to_assess" if unable else "complete",
                overall_priority=priority,
                summary=summary,
                findings=[],
                limitations=limitations,
                error_message=unable_reason if unable else "",
                completed_at=timezone.now(),
            )
            classification.analysis = result
            classification.save(update_fields=["analysis"])
            _ensure_review_record(classification)
            document.status = result.status
            document.save(update_fields=["status"])
            return Response(AnalysisSerializer(result).data, status=201)
        try:
            report, unable, completed_model = analyze_text(document.extracted_text, model)
            if report:
                report = attach_evidence_references(report, document.extracted_text)
            if not re.sub(r"\[Page\s+\d+\]\s*", "", document.extracted_text).strip(): unable = "No readable text could be extracted. This may be a scanned PDF; OCR is required."
            if unable:
                classification.status = "unable_to_assess"
                classification.predicted_label = None
                classification.class_scores = {}
                classification.review_required = True
                classification.review_reasons = [unable, "Classifier priority withheld because the document could not be meaningfully assessed."]
            elif report and classification.status == "complete" and classification.predicted_label != report["overall_priority"]:
                classification.review_required = True
                classification.review_reasons = [
                    *classification.review_reasons,
                    "Classifier and LLM review priorities differ; human review is required.",
                ]
            classification.save(update_fields=["status", "predicted_label", "class_scores", "review_required", "review_reasons"])
            _ensure_review_record(classification)
            result = Analysis.objects.create(document=document, selected_model=completed_model, status="unable_to_assess" if unable else "complete", overall_priority=report["overall_priority"] if report else None, summary=report["summary"] if report else unable, findings=report["findings"] if report else [], limitations=report["limitations"] if report else [unable], error_message=unable or "", completed_at=timezone.now())
            classification.analysis = result; classification.save(update_fields=["analysis"])
            document.status = result.status; document.document_type = report["document_type"] if report else ""; document.save(update_fields=["status","document_type"])
            return Response(AnalysisSerializer(result).data, status=201)
        except ProviderError as exc:
            failed_result = Analysis.objects.create(document=document, selected_model=model, status="failed", error_message=str(exc), summary="Analysis could not be completed.", limitations=["No valid report was produced; no risk priority was assigned."], completed_at=timezone.now())
            classification.analysis = failed_result; classification.save(update_fields=["analysis"])
            _ensure_review_record(classification)
            document.status = "failed"; document.save(update_fields=["status"])
            return Response({"detail":str(exc)}, status=502)
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        doc = self.get_object()
        return Response({"text":doc.extracted_text[:12000],"truncated":len(doc.extracted_text)>12000})


class AskAIView(APIView):
    """Optional, on-demand LLM Q&A for a stored document or general questions."""
    def post(self, request):
        question = request.data.get("question", "")
        model = request.data.get("model", "")
        document_id = request.data.get("document_id")
        history = request.data.get("history", [])
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            return Response({"detail":"Enter a question between 1 and 4000 characters."}, status=400)
        if not isinstance(history, list) or len(history) > 10 or any(
            not isinstance(item, dict)
            or item.get("role") not in {"user", "assistant"}
            or not isinstance(item.get("content"), str)
            or len(item["content"]) > 4000
            for item in history
        ):
            return Response({"detail":"Conversation history is invalid. Start a new Ask AI conversation."}, status=400)
        if model not in settings.ANALYSIS_MODELS:
            return Response({"detail":"Select an available configured model."}, status=400)

        document = None
        if document_id not in (None, ""):
            try:
                document = Document.objects.get(pk=document_id)
            except (Document.DoesNotExist, ValueError, TypeError):
                return Response({"detail":"The selected document could not be found."}, status=404)
            if not document.extracted_text.strip():
                return Response({"detail":"This document has no readable extracted text. Scanned PDFs require OCR before Ask AI can use them."}, status=400)
        try:
            answer, used_model = answer_question(
                question,
                document.extracted_text if document else "",
                model,
                history,
            )
        except ProviderError as exc:
            return Response({"detail":str(exc)}, status=502)
        except Exception as exc:
            logger.warning("Ask AI request failed (type=%s)", type(exc).__name__)
            return Response({"detail":"Ask AI could not complete this request. Retry or choose another configured model."}, status=502)
        return Response({
            "answer":answer,
            "model":used_model,
            "document_id":document.pk if document else None,
            "document_name":document.original_filename if document else "",
        })

class AnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalysisSerializer
    def get_queryset(self):
        qs = Analysis.objects.select_related("document", "classification")
        q = self.request.query_params.get("search")
        if q: qs = qs.filter(document__original_filename__icontains=q)
        for key, field in [("priority","overall_priority"),("type","document__file_type"),("model","selected_model")]:
            value = self.request.query_params.get(key)
            if value: qs = qs.filter(**{field:value})
        start, end = self.request.query_params.get("start"), self.request.query_params.get("end")
        if start: qs = qs.filter(created_at__date__gte=start)
        if end: qs = qs.filter(created_at__date__lte=end)
        ordering = self.request.query_params.get("ordering")
        allowed_orderings = {"created_at", "-created_at", "overall_priority", "-overall_priority", "document__original_filename", "-document__original_filename"}
        if ordering in allowed_orderings: qs = qs.order_by(ordering)
        return qs
    @action(detail=True, methods=["get"], url_path="export/json")
    def export_json(self, request, pk=None):
        item = self.get_object(); data = AnalysisSerializer(item).data
        response = HttpResponse(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="docuguard-report-{item.pk}.json"'; return response
    @action(detail=True, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request, pk=None):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        item = self.get_object(); buffer = BytesIO(); pdf = canvas.Canvas(buffer, pagesize=letter); y = 750
        def line(text):
            nonlocal y
            parts = [wrapped for raw in str(text).splitlines() or [""] for wrapped in (textwrap.wrap(raw, width=96, break_long_words=True) or [""])]
            for part in parts:
                if y < 55: pdf.showPage(); y = 750
                pdf.drawString(48, y, part); y -= 16
        line("DocuGuard AI — Document Review Report"); line(item.document.original_filename); line(f"Date: {item.created_at:%Y-%m-%d %H:%M UTC} | Model: {item.selected_model}")
        line(f"Status: {item.status} | Priority: {item.overall_priority or 'Not assessed'}"); line(""); line("Summary"); line(item.summary)
        try:
            classification = item.classification
            line(f"Classifier prediction: {classification.predicted_label or classification.status} | Version: {classification.classifier_version or 'unavailable'}")
            line("Classifier class scores: " + json.dumps(classification.class_scores, ensure_ascii=False))
            for review_reason in classification.review_reasons:
                line(f"Model review reason: {review_reason}")
            try:
                decision = classification.review_decision
                line(f"Human review status: {decision.status} | Human-assessed class: {decision.final_label or 'not recorded'}")
                if decision.note: line(f"Reviewer note: {decision.note}")
            except ClassificationReview.DoesNotExist:
                line("Human review status: no manual review decision recorded")
        except DocumentClassification.DoesNotExist:
            pass
        for idx, finding in enumerate(item.findings, 1):
            line(f"Finding {idx}: {finding['issue']} ({finding['severity']})"); line(f"Evidence: {finding['evidence']}")
            if finding.get("evidence_verified"):
                line(f"Source reference: {', '.join(finding.get('source_references', [])) or 'Text excerpt'} (matched extracted text)")
            elif finding.get("evidence_verified") is False:
                line("Source reference: excerpt could not be matched; verify manually")
            line(f"Why it matters: {finding['explanation']}"); line(f"Suggested action: {finding['recommended_action']}")
        line("Limitations"); [line(f"- {x}") for x in item.limitations]; line("Human verification is required. This report is not legal advice and does not certify compliance.")
        pdf.save(); response = HttpResponse(buffer.getvalue(), content_type="application/pdf"); response["Content-Disposition"] = f'attachment; filename="docuguard-report-{item.pk}.pdf"'; return response
    @action(detail=True, methods=["delete"])
    def delete(self, request, pk=None):
        item = self.get_object(); document = item.document; storage, name = document.file.storage, document.file.name
        document.delete()
        if name: storage.delete(name)
        return Response(status=204)

class ReviewQueueViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReviewQueueSerializer
    queryset = DocumentClassification.objects.none()

    def get_queryset(self):
        qs = DocumentClassification.objects.select_related("document", "analysis", "review_decision").annotate(
            top_class_score=Case(
                When(predicted_label="Low", then=Cast(F("class_scores__Low"), FloatField())),
                When(predicted_label="Medium", then=Cast(F("class_scores__Medium"), FloatField())),
                When(predicted_label="High", then=Cast(F("class_scores__High"), FloatField())),
                default=None,
                output_field=FloatField(),
            )
        ).filter(
            review_required=True, review_decision__isnull=False
        )
        review_status = self.request.query_params.get("status")
        if review_status in {choice[0] for choice in ClassificationReview.STATUS}:
            qs = qs.filter(review_decision__status=review_status)
        priority = self.request.query_params.get("priority")
        if priority in {choice[0] for choice in DocumentClassification.PRIORITY}:
            qs = qs.filter(predicted_label=priority)
        score_band = self.request.query_params.get("score_band")
        if score_band == "low":
            qs = qs.filter(top_class_score__lt=0.5)
        elif score_band == "medium":
            qs = qs.filter(top_class_score__gte=0.5, top_class_score__lt=0.75)
        elif score_band == "high":
            qs = qs.filter(top_class_score__gte=0.75)
        elif score_band == "unknown":
            qs = qs.filter(top_class_score__isnull=True)
        reason = self.request.query_params.get("reason", "").strip()
        if reason:
            qs = qs.filter(review_reasons__icontains=reason)
        start, end = self.request.query_params.get("start"), self.request.query_params.get("end")
        if start:
            qs = qs.filter(created_at__date__gte=start)
        if end:
            qs = qs.filter(created_at__date__lte=end)
        ordering = self.request.query_params.get("ordering", "-created_at")
        if ordering in {"created_at", "-created_at", "predicted_label", "-predicted_label"}:
            qs = qs.order_by(ordering)
        return qs

    @action(detail=True, methods=["post"], url_path="decision")
    def decision(self, request, pk=None):
        classification = self.get_object()
        try:
            review = classification.review_decision
        except ClassificationReview.DoesNotExist:
            return Response({"detail": "This classification is not in the manual-review queue."}, status=status.HTTP_404_NOT_FOUND)
        state = request.data.get("status")
        allowed_states = {choice[0] for choice in ClassificationReview.STATUS}
        if state not in allowed_states:
            return Response({"status": "Choose needs_review, reviewed, or dismissed."}, status=status.HTTP_400_BAD_REQUEST)
        final_label = request.data.get("final_label") or None
        valid_labels = {choice[0] for choice in DocumentClassification.PRIORITY}
        if state == "reviewed" and final_label not in valid_labels:
            return Response({"final_label": "Choose a final Low, Medium, or High review label."}, status=status.HTTP_400_BAD_REQUEST)
        if state == "needs_review" and final_label:
            return Response({"final_label": "A reopened case cannot retain a final label."}, status=status.HTTP_400_BAD_REQUEST)
        if final_label and final_label not in valid_labels:
            return Response({"final_label": "Choose Low, Medium, or High."}, status=status.HTTP_400_BAD_REQUEST)
        note = request.data.get("note", "")
        if not isinstance(note, str) or len(note) > 2000:
            return Response({"note": "Review note must be 2,000 characters or fewer."}, status=status.HTTP_400_BAD_REQUEST)
        review.status, review.final_label, review.note = state, final_label, note.strip()
        review.save(update_fields=["status", "final_label", "note", "updated_at"])
        return Response(ReviewQueueSerializer(classification).data)


class DashboardView(APIView):
    def get(self, request):
        docs = Document.objects.all(); analyses = Analysis.objects.select_related("document")
        latest_classification = DocumentClassification.objects.filter(document_id=OuterRef("pk")).order_by("-created_at", "-pk").values("pk")[:1]
        latest_ids = Document.objects.annotate(latest_classification_id=Subquery(latest_classification)).values_list("latest_classification_id", flat=True)
        current_predictions = DocumentClassification.objects.filter(pk__in=latest_ids, status="complete", predicted_label__isnull=False)
        reviews = ClassificationReview.objects.select_related("classification__document").order_by("-updated_at")
        return Response({
            "total_documents":analyses.filter(status__in=["complete","unable_to_assess"]).values("document_id").distinct().count(),
            "awaiting_review":docs.filter(status__in=["uploaded","analyzing"]).count(),
            "high_priority":analyses.filter(overall_priority="High",status="complete").count(),
            "priority_distribution":list(analyses.filter(status="complete").values("overall_priority").annotate(count=Count("id"))),
            "predicted_distribution":list(current_predictions.values("predicted_label").annotate(count=Count("id"))),
            "manual_review_backlog":reviews.filter(status="needs_review",classification__review_required=True).count(),
            "reviewed_count":reviews.filter(status="reviewed").count(),
            "dismissed_count":reviews.filter(status="dismissed").count(),
            "recent_review_decisions":ReviewActivitySerializer(reviews.exclude(status="needs_review")[:5],many=True).data,
            "recent_analyses":AnalysisSerializer(analyses[:5],many=True).data,
            "recent_activity":DocumentSerializer(docs[:8],many=True).data,
        })


class ModelPerformanceView(APIView):
    """Expose the latest local sealed evaluation without exposing artifact paths."""
    def get(self, request):
        configured = str(getattr(settings, "CLASSIFIER_MODEL_PATH", "") or "").strip()
        if not configured:
            return Response({"available": False, "detail": "No classifier artifact is configured."})
        model_path = Path(configured).expanduser()
        if not model_path.is_absolute():
            model_path = settings.BASE_DIR.parent / model_path
        try:
            report = json.loads(model_path.resolve().with_name("evaluation_report.json").read_text(encoding="utf-8"))
            metadata = json.loads(model_path.resolve().with_name("metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Response({"available": False, "detail": "The configured classifier has no readable sealed evaluation report."})
        return Response({
            "available": True,
            "model_version": report.get("model_version"),
            "evaluated_at_utc": report.get("evaluated_at_utc"),
            "corpus_approval_mode": metadata.get("corpus_approval_mode"),
            "rubric_version": metadata.get("rubric_version"),
            "showcase_nonproduction": bool(metadata.get("showcase_nonproduction")),
            "promotion_status": metadata.get("promotion_status"),
            "test_support": report.get("test_support", 0),
            "test_class_counts": report.get("test_class_counts", {}),
            "class_order": report.get("class_order", []),
            "scores_calibrated": report.get("scores_calibrated", False),
            "test_metrics": report.get("test_metrics", {}),
            "test_calibration": report.get("test_calibration", {}),
            "test_review_routing": report.get("test_review_routing", {}),
            "promotion_gate": report.get("promotion_gate", {"status": "blocked", "blocking_reasons": ["No gate report found."]}),
            "limitations": report.get("limitations", []),
        })

class SettingsView(APIView):
    def response_data(self, preferences):
        return {
            **SettingsSerializer(preferences).data,
            "models":settings.ANALYSIS_MODELS,
            "provider_configured":bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY),
            "providers":{"gemini_configured":bool(settings.GEMINI_API_KEY),"groq_configured":bool(settings.GROQ_API_KEY)},
            "fallback_model":f"groq:{settings.GROQ_FALLBACK_MODEL}",
            "max_upload_mb":settings.MAX_UPLOAD_MB,
            "classifier":{"configured":bool(settings.CLASSIFIER_MODEL_PATH),"candidate_allowed":settings.CLASSIFIER_ALLOW_CANDIDATE,"min_words":settings.CLASSIFIER_MIN_WORDS},
        }
    def get(self, request):
        preferences, _ = WorkspaceSettings.objects.get_or_create(pk=1, defaults={"default_model":settings.GEMINI_DEFAULT_MODEL})
        return Response(self.response_data(preferences))
    def patch(self, request):
        preferences, _ = WorkspaceSettings.objects.get_or_create(pk=1, defaults={"default_model":settings.GEMINI_DEFAULT_MODEL})
        serializer = SettingsSerializer(preferences, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
        if "default_model" in serializer.validated_data and serializer.validated_data["default_model"] not in settings.ANALYSIS_MODELS: return Response({"default_model":"Choose a configured model."}, status=400)
        serializer.save(); return Response(self.response_data(preferences))
