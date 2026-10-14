from rest_framework import serializers
from .models import Document, Analysis, DocumentClassification, ClassificationReview, WorkspaceSettings


class ClassificationReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassificationReview
        fields = ["status", "final_label", "note", "updated_at"]
        read_only_fields = ["updated_at"]


class ClassificationSerializer(serializers.ModelSerializer):
    review_decision = serializers.SerializerMethodField()

    class Meta:
        model = DocumentClassification
        fields = [
            "id", "status", "predicted_label", "class_scores", "classifier_version",
            "feature_signals", "nearest_examples", "review_required", "review_reasons", "review_decision", "created_at",
        ]

    def get_review_decision(self, obj):
        try:
            return ClassificationReviewSerializer(obj.review_decision).data
        except ClassificationReview.DoesNotExist:
            return None


class ReviewQueueSerializer(serializers.ModelSerializer):
    document_name = serializers.CharField(source="document.original_filename", read_only=True)
    file_type = serializers.CharField(source="document.file_type", read_only=True)
    analysis_id = serializers.SerializerMethodField()
    analysis_summary = serializers.SerializerMethodField()
    review_status = serializers.CharField(source="review_decision.status", read_only=True)
    review_note = serializers.CharField(source="review_decision.note", read_only=True)
    final_label = serializers.CharField(source="review_decision.final_label", read_only=True)
    review_updated_at = serializers.DateTimeField(source="review_decision.updated_at", read_only=True)
    top_class_score = serializers.SerializerMethodField()

    class Meta:
        model = DocumentClassification
        fields = ["id", "document_name", "file_type", "analysis_id", "analysis_summary", "status", "predicted_label", "top_class_score", "class_scores", "classifier_version", "review_reasons", "review_required", "review_status", "review_note", "final_label", "review_updated_at", "created_at"]

    def get_analysis_id(self, obj):
        return obj.analysis_id

    def get_analysis_summary(self, obj):
        return obj.analysis.summary if obj.analysis_id else ""

    def get_top_class_score(self, obj):
        return (obj.class_scores or {}).get(obj.predicted_label)


class ReviewActivitySerializer(serializers.ModelSerializer):
    classification_id = serializers.IntegerField(read_only=True)
    document_name = serializers.CharField(source="classification.document.original_filename", read_only=True)
    predicted_label = serializers.CharField(source="classification.predicted_label", read_only=True)

    class Meta:
        model = ClassificationReview
        fields = ["classification_id", "document_name", "predicted_label", "status", "final_label", "note", "updated_at"]


class AnalysisSerializer(serializers.ModelSerializer):
    document_name = serializers.CharField(source="document.original_filename", read_only=True)
    document_type = serializers.CharField(source="document.file_type", read_only=True)
    detected_document_type = serializers.CharField(source="document.document_type", read_only=True)
    classification = serializers.SerializerMethodField()

    class Meta:
        model = Analysis
        fields = ["id", "document_id", "document_name", "document_type", "detected_document_type", "selected_model", "status", "overall_priority", "summary", "findings", "limitations", "error_message", "created_at", "completed_at", "classification"]

    def get_classification(self, obj):
        try:
            return ClassificationSerializer(obj.classification).data
        except DocumentClassification.DoesNotExist:
            return None


class DocumentSerializer(serializers.ModelSerializer):
    latest_analysis = serializers.SerializerMethodField()
    latest_classification = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ["id", "original_filename", "file_type", "file_size", "uploaded_at", "status", "document_type", "latest_analysis", "latest_classification"]

    def get_latest_analysis(self, obj):
        item = obj.analyses.first()
        return AnalysisSerializer(item).data if item else None

    def get_latest_classification(self, obj):
        item = obj.classifications.order_by("-created_at", "-pk").first()
        return ClassificationSerializer(item).data if item else None


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkspaceSettings
        fields = ["default_model", "theme"]
