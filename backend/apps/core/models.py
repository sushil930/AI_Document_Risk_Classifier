from django.db import models


class WorkspaceSettings(models.Model):
    default_model = models.CharField(max_length=120, default="gemini-3.8-flash")
    theme = models.CharField(max_length=10, choices=[("light", "Light"), ("dark", "Dark")], default="light")


class Document(models.Model):
    STATUS = [("uploaded", "Uploaded"), ("analyzing", "Analyzing"), ("complete", "Complete"), ("unable_to_assess", "Unable to assess"), ("failed", "Failed")]
    file = models.FileField(upload_to="documents/%Y/%m/", max_length=255)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)
    file_size = models.PositiveBigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=24, choices=STATUS, default="uploaded", db_index=True)
    document_type = models.CharField(max_length=120, blank=True)
    extracted_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at"]


class Analysis(models.Model):
    STATUS = [("complete", "Complete"), ("unable_to_assess", "Unable to assess"), ("failed", "Failed")]
    PRIORITY = [("Low", "Low"), ("Medium", "Medium"), ("High", "High")]
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="analyses")
    selected_model = models.CharField(max_length=120)
    status = models.CharField(max_length=24, choices=STATUS, db_index=True)
    overall_priority = models.CharField(max_length=10, choices=PRIORITY, null=True, blank=True)
    summary = models.TextField(blank=True)
    findings = models.JSONField(default=list)
    limitations = models.JSONField(default=list)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class DocumentClassification(models.Model):
    STATUS = [
        ("complete", "Complete"),
        ("unable_to_assess", "Unable to assess"),
        ("unavailable", "Unavailable"),
    ]
    PRIORITY = [("Low", "Low"), ("Medium", "Medium"), ("High", "High")]
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="classifications")
    analysis = models.OneToOneField(
        Analysis,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classification",
    )
    status = models.CharField(max_length=24, choices=STATUS, db_index=True)
    predicted_label = models.CharField(max_length=10, choices=PRIORITY, null=True, blank=True)
    class_scores = models.JSONField(default=dict)
    feature_signals = models.JSONField(default=dict)
    nearest_examples = models.JSONField(default=list)
    classifier_version = models.CharField(max_length=100, blank=True, db_index=True)
    review_required = models.BooleanField(default=True, db_index=True)
    review_reasons = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class ClassificationReview(models.Model):
    STATUS = [("needs_review", "Needs review"), ("reviewed", "Reviewed"), ("dismissed", "Dismissed")]
    classification = models.OneToOneField(DocumentClassification, on_delete=models.CASCADE, related_name="review_decision")
    status = models.CharField(max_length=20, choices=STATUS, default="needs_review", db_index=True)
    final_label = models.CharField(max_length=10, choices=DocumentClassification.PRIORITY, null=True, blank=True)
    note = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]
