from rest_framework import viewsets

from ..models import Branch
from ..selectors import branches
from .serializers import BranchSerializer


class BranchViewSet(viewsets.ReadOnlyModelViewSet):
    """Branches you work in: every branch for a super admin, otherwise your own."""

    serializer_class = BranchSerializer
    queryset = Branch.objects.none()  # for the schema; get_queryset() is the real scope
    search_fields = ["name", "code", "city"]

    def get_queryset(self):
        return branches(self.request.user).order_by("name", "pk")
