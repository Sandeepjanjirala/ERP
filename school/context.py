from .models import Organization

def portal(request):
    return {'organization': Organization.objects.first(), 'is_manager': request.user.is_authenticated and request.user.role in ('superadmin','admin'), 'is_leader': request.user.is_authenticated and request.user.role in ('superadmin','admin','principal')}
