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
        # A view may add a directive the base policy doesn't set (response.csp_extra). Browsers
        # use the first copy of a repeated directive, so an addition can't loosen one above.
        extra = getattr(response, "csp_extra", "")
        response["Content-Security-Policy"] = "; ".join(
            filter(None, [self.CONTENT_SECURITY_POLICY, extra])
        )
        response["Referrer-Policy"] = "same-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # API callers authenticate with a token the middleware can't see, so API responses
        # (which may contain tokens or private records) are never cached either.
        if request.user.is_authenticated or request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, private"
        return response
