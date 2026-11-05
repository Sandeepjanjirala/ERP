"""OpenAPI schema and the two documentation pages, served from our own static files."""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
)

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    # The split view serves its start-up script as a separate file, so no inline script is needed
    # and the Content-Security-Policy can stay "script-src 'self'".
    path("docs/", SpectacularSwaggerSplitView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
