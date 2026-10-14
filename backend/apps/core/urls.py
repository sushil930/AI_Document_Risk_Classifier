from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AskAIView, DocumentViewSet, DashboardView, ModelPerformanceView, SettingsView, LocalReportPDFView
router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")
urlpatterns = [path("dashboard/", DashboardView.as_view()), path("model-performance/", ModelPerformanceView.as_view()), path("settings/", SettingsView.as_view()), path("ask-ai/", AskAIView.as_view()), path("export/pdf-local/", LocalReportPDFView.as_view()), path("", include(router.urls))]
