class SecurityHeadersMiddleware:
    """Add browser security headers to every response, and never cache signed-in pages."""

    # Directive -> allowed sources. Directives not listed fall back to default-src.
    CSP = {
        "default-src": ("'self'",),
        "style-src": ("'self'", "'unsafe-inline'"),
        "script-src": ("'self'",),
        "img-src": ("'self'", "data:"),
        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
        "frame-ancestors": ("'none'",),
    }

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def policy(cls, additions=None):
        """The policy with a page's additions merged into each directive.

        A page that needs more (ReDoc's blob: worker, the Razorpay checkout) sets
        response.csp_add = {"script-src": ["https://..."]}. Sources are only ever added, and a
        directive the base policy sets to 'none' can't be opened by a page at all.
        """
        directives = {name: list(sources) for name, sources in cls.CSP.items()}
        for name, sources in (additions or {}).items():
            current = directives.setdefault(name, list(cls.CSP["default-src"]))
            if current == ["'none'"]:
                raise ValueError(f"{name} is 'none' for every page and can't be extended.")
            current.extend(source for source in sources if source not in current)
        return "; ".join(f"{name} {' '.join(sources)}" for name, sources in directives.items())

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self.policy(getattr(response, "csp_add", None))
        response["Referrer-Policy"] = "same-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # API callers authenticate with a token the middleware can't see, so API responses
        # (which may contain tokens or private records) are never cached either.
        if request.user.is_authenticated or request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, private"
        return response
