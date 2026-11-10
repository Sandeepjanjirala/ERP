import hashlib

from django.core.cache import cache


def cached(name, parts, compute, timeout=60 * 60):
    """compute() once per distinct `parts`, then from the cache (Redis when configured).

    Put into `parts` everything the answer depends on, including a data version that changes
    when the underlying rows change. A changed version is a new key, so stale numbers are never
    served and nothing has to delete keys; old keys simply expire.
    """
    raw = ":".join(str(part) for part in parts)
    key = f"{name}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"
    return cache.get_or_set(key, compute, timeout)
