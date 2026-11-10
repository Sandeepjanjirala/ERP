"""Static files build with the manifest storage production uses.

Tests otherwise use plain storage, which never follows references between files. Production's
storage rewrites every url(...) and sourceMappingURL to a versioned name, and fails if a
referenced file is missing, which would stop the web container from starting.
"""

import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class StaticBuildTests(SimpleTestCase):
    def test_collectstatic_with_the_production_storage(self):
        with tempfile.TemporaryDirectory() as root:
            storages = {
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                # The same file processing as production's WhiteNoise storage, minus compression.
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
                },
            }
            with override_settings(STATIC_ROOT=root, STORAGES=storages):
                call_command("collectstatic", interactive=False, verbosity=0, stdout=StringIO())
