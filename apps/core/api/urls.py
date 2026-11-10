"""OpenAPI schema and the two documentation pages, served from our own static files."""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
)


class RedocView(SpectacularRedocView):
    """ReDoc builds its search index in a Web Worker made from a blob: URL, and styles itself
    with <style> tags it writes. Allow both on this page only."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response.csp_add = {"worker-src": ["blob:"], "style-src": ["'unsafe-inline'"]}
        return response


class SwaggerView(SpectacularSwaggerSplitView):
    """Swagger UI sets inline styles as it draws. Allow them on this page only."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response.csp_add = {"style-src": ["'unsafe-inline'"]}
        return response


urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    # The split view serves its start-up script as a separate file, so no inline script is needed
    # and the Content-Security-Policy can stay "script-src 'self'".
    path("docs/", SwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", RedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
