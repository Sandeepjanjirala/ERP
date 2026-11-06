from rest_framework.filters import OrderingFilter


class StableOrderingFilter(OrderingFilter):
    """`?ordering=` only on fields a view lists in `ordering_fields`, always ending with the pk.

    When a view lists none, DRF's default accepts every serializer field's source, including
    model methods such as `get_role_display`, which are not database columns (a 500). Here a
    view that declares nothing allows no sorting. A sort on a column with repeated values (first
    names) could let pages repeat or skip rows, so the primary key is added as the final
    tiebreak. Without `?ordering=`, the list keeps its selector's own stable order.
    """

    def get_valid_fields(self, queryset, view, context=None):
        return [(field, field) for field in getattr(view, "ordering_fields", None) or ()]

    def get_ordering(self, request, queryset, view):
        params = request.query_params.get(self.ordering_param)
        if params:
            terms = [term.strip() for term in params.split(",")]
            fields = self.remove_invalid_fields(queryset, terms, view, request)
            if fields:
                return [*fields, "pk"]
        return None

    def get_schema_operation_parameters(self, view):
        # Only endpoints that allow sorting document the parameter.
        if not getattr(view, "ordering_fields", None):
            return []
        return super().get_schema_operation_parameters(view)
