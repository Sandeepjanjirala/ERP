class SecurityHeadersMiddleware:
    """Add browser security headers to every response, and never cache signed-in pages."""

    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self.CONTENT_SECURITY_POLICY
        response["Referrer-Policy"] = "same-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # API callers authenticate with a token the middleware can't see, so API responses
        # (which may contain tokens or private records) are never cached either.
        if request.user.is_authenticated or request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, private"
        return response
