"""Small template helpers shared by every page: icons, navigation state and audit details."""

import json

from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def icon(name, label="", css=""):
    """An icon from static/img/icons.svg. Decorative (hidden from screen readers) unless labelled."""
    href = f"{static('img/icons.svg')}#{name}"
    classes = f"icon {css}".strip()
    if label:
        return format_html(
            '<svg class="{}" role="img" aria-label="{}"><use href="{}"></use></svg>',
            classes,
            label,
            href,
        )
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}"></use></svg>',
        classes,
        href,
    )


@register.simple_tag(takes_context=True)
def aria_current(context, *url_names):
    """Mark a navigation link as the current page when the request matches one of its URL names."""
    match = getattr(context.get("request"), "resolver_match", None)
    return mark_safe(' aria-current="page"') if match and match.url_name in url_names else ""


@register.filter
def pretty_json(value):
    """Indented JSON for audit details, so before/after values are easy to compare."""
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
