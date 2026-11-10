"""The container health check: is the app answering /health/ (which also checks the database)?

It asks as the reverse proxy would (the site's own host name, already HTTPS), so production's
host check and HTTPS redirect apply to it like to any request. Exit 0 when healthy.
"""

import os
import sys
import urllib.request

host = (os.getenv("ALLOWED_HOSTS") or "localhost").split(",")[0].strip()
request = urllib.request.Request(
    "http://127.0.0.1:8000/health/", headers={"Host": host, "X-Forwarded-Proto": "https"}
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception as error:  # noqa: BLE001 - any failure means unhealthy
    print(f"unhealthy: {error}", file=sys.stderr)
    sys.exit(1)
