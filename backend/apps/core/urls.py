from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AskAIView, DocumentViewSet, AnalysisViewSet, ReviewQueueViewSet, DashboardView, ModelPerformanceView, SettingsView
router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")
router.register("analyses", AnalysisViewSet, basename="analysis")
router.register("reviews", ReviewQueueViewSet, basename="review")
urlpatterns = [path("dashboard/", DashboardView.as_view()), path("model-performance/", ModelPerformanceView.as_view()), path("settings/", SettingsView.as_view()), path("ask-ai/", AskAIView.as_view()), path("", include(router.urls))]
