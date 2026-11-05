import unicodedata
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import LoginAttempt


def throttle(namespace, value, limit=8, minutes=15):
    normalized = unicodedata.normalize("NFKC", value).strip().lower()[:300]
    key = salted_hmac(namespace, normalized).hexdigest()
    with transaction.atomic():
        LoginAttempt.objects.get_or_create(key=key, defaults={"started_at": timezone.now()})
        record = LoginAttempt.objects.select_for_update().get(pk=key)
        if record.started_at <= timezone.now() - timedelta(minutes=minutes):
            record.count, record.started_at = 0, timezone.now()
        if record.count >= limit:
            return False, key
        record.count += 1
        record.save()
    return True, key
