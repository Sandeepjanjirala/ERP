from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(OpenApiTypes.INT)
class ScopedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """An id that must be one of the caller's own records, as a selector defines them.

    `ScopedPrimaryKeyField(classrooms)` accepts only ids from `classrooms(request.user)`; any
    other id gets the same "does not exist" error as a missing one, so it reveals nothing.
    """

    def __init__(self, selector, **kwargs):
        self.selector = selector
        super().__init__(**kwargs)

    def get_queryset(self):
        return self.selector(self.context["request"].user)
