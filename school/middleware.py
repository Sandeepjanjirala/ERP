from django.shortcuts import redirect
from django.urls import reverse

class PortalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        allowed = {reverse('password_change'), reverse('password_change_done'), reverse('logout')}
        if request.user.is_authenticated and request.user.must_change_password and request.path not in allowed and not request.path.startswith('/static/'):
            return redirect('password_change')
        response = self.get_response(request)
        response['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-store, private'
        return response
