"""OpenAPI schema and the two documentation pages, served from our own static files."""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
)


class RedocView(SpectacularRedocView):
    """ReDoc builds its search index in a Web Worker made from a blob: URL. Allow that here only."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response.csp_add = {"worker-src": ["blob:"]}
        return response


urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    # The split view serves its start-up script as a separate file, so no inline script is needed
    # and the Content-Security-Policy can stay "script-src 'self'".
    path("docs/", SpectacularSwaggerSplitView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", RedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
