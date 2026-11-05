from django.conf import settings


def brand(request):
    """The product identity (EduNexa) for every template."""
    return {"brand": settings.BRAND}
