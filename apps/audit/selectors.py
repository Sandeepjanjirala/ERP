"""Read queries for the activity log, already limited to what the user may see."""

from django.db.models import Q

from .models import AuditEvent


def events(user):
    """Everything for super admins; otherwise only the user's branch."""
    queryset = AuditEvent.objects.select_related("actor", "branch")
    if not user.system_admin:
        queryset = queryset.filter(branch=user.branch)
    return queryset


def event_areas(queryset):
    """The parts of the school the events are about ("exam", "fees", ...): the text before the
    first dot of each action, for the area filter."""
    actions = queryset.order_by().values_list("action", flat=True).distinct()
    return sorted({action.split(".", 1)[0] for action in actions})


def filter_events(
    queryset, area="", action="", person="", since=None, until=None, text="", request=""
):
    """The activity log narrowed by any of: an area ("exam"), an action ("exam.publish"), a
    person (name or username), a date range, words in the record, a request id."""
    if area:
        queryset = queryset.filter(Q(action=area) | Q(action__startswith=f"{area}."))
    if action:
        queryset = queryset.filter(action__startswith=action)
    if person:
        queryset = queryset.filter(
            Q(actor__username__icontains=person)
            | Q(actor__first_name__icontains=person)
            | Q(actor__last_name__icontains=person)
        )
    if since:
        queryset = queryset.filter(created_at__date__gte=since)
    if until:
        queryset = queryset.filter(created_at__date__lte=until)
    if text:
        queryset = queryset.filter(target__icontains=text)
    if request:
        queryset = queryset.filter(request_id=request.strip().lower())
    return queryset
