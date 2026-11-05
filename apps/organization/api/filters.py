"""Filter choices limited to the caller's scope, so ?branch=<another branch> is rejected (400)."""

from ..models import Branch
from ..selectors import branches


def scoped_branches(request):
    # The schema generator calls this without a request.
    return branches(request.user) if request else Branch.objects.none()
