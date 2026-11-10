from django import template

from apps.fees.models import rupees as format_rupees

register = template.Library()


@register.filter
def rupees(paise):
    """{{ invoice.total_paise|rupees }} -> ₹12,500.00"""
    return "" if paise in (None, "") else format_rupees(int(paise))
