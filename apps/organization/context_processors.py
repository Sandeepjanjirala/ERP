from .models import Organization


def workspace(request):
    """The school group, shown as the workspace name. It is data, not the product brand."""
    return {"organization": Organization.objects.first()}
