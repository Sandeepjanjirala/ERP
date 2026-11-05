from rest_framework import pagination


class PageNumberPagination(pagination.PageNumberPagination):
    """`?page=2&page_size=50`. Every list orders by a unique column last, so pages never overlap."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
