from django.core.paginator import Paginator


def paginate(request, queryset, per_page=25):
    """The page named by ?page=; invalid or out-of-range values fall back to a valid page."""
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))
