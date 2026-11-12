from django.urls import path, include
from apps.core.views import health, health_check
urlpatterns = [path("health", health_check), path("api/health/", health), path("api/", include("apps.core.urls"))]
