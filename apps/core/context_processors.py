from django.conf import settings


def brand(request):
    """The product identity (EduNexa) for every template, and whether this is the demo."""
    return {"brand": settings.BRAND, "demo_mode": settings.DEMO_MODE}
