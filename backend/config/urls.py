from django.urls import path, include
from apps.core.views import health
urlpatterns = [path("api/health/", health), path("api/", include("apps.core.urls"))]
