from django.conf import settings

from .models import Organization


def portal(request):
    return {
        "brand": settings.BRAND,
        "organization": Organization.objects.first(),
        "is_manager": request.user.is_authenticated
        and request.user.role in ("superadmin", "admin"),
        "is_leader": request.user.is_authenticated
        and request.user.role in ("superadmin", "admin", "principal"),
    }
